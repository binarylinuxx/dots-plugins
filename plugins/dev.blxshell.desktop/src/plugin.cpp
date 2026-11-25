// Desktop icons for blxshell: what's in your desktop folder, on the wallpaper.
//
// Click an icon for its actions: open it, open it with another app, show it in
// its folder, copy its path, move it to the trash. Double-click opens it.
// .desktop launchers show their app's name and icon and run it.
//
// A native plugin: the shell loads lib/plugin.so. Apps (names, icons,
// launching, "Open with") come from vw's applications service through the
// host. A worker thread watches the folder with inotify and sends the items
// with Host::desktop, the one host call that's safe off the shell's thread
// besides Host::applications.
#include <blxshell/plugin.hpp>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <optional>
#include <poll.h>
#include <sstream>
#include <string>
#include <sys/eventfd.h>
#include <sys/inotify.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {

namespace fs = std::filesystem;
using nlohmann::json;

constexpr const char* area = "files";
constexpr std::uintmax_t thumbnail_limit = 15U * 1024U * 1024U;

const std::vector<std::string> shapes{"none", "circle", "square", "cookie4sided", "cookie6sided", "cookie7sided",
                                      "cookie9sided", "cookie12sided", "clover4leaf", "clover8leaf", "sunny",
                                      "verysunny", "softburst", "flower", "puffy", "pentagon", "gem", "diamond",
                                      "arch", "slanted", "pill", "ghostish", "bun", "heart"};

struct Settings {
  std::string folder;  // "" is the XDG desktop folder (~/Desktop)
  bool show_hidden = false;
  std::string sort = "name";  // name, modified, type
  bool folders_first = true;
  int other_apps = 4;           // "Open with" entries per file
  std::string shape = "none";   // a Material shape the icons sit on
  std::string tint = "none";    // none, colour, themed
  bool operator==(const Settings&) const = default;
};

// An installed application, from Host::applications.
struct App {
  std::string name;
  std::string icon;
  std::string icon_path;
};

// A launcher on the desktop that isn't an installed app: what its file says.
struct Entry {
  std::string name;
  std::string icon;
  std::string exec;
  bool terminal = false;
};

// What an item's actions need.
struct Detail {
  fs::path path;
  std::string mime;
  std::string app;               // an installed app's id, for a launcher
  std::optional<Entry> launcher;  // a launcher file that isn't installed
};

std::string home() {
  const char* value = std::getenv("HOME");
  return value != nullptr ? value : "/";
}

std::string lowercase(std::string text) {
  std::ranges::transform(text, text.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return text;
}

std::vector<fs::path> data_dirs() {
  std::vector<fs::path> dirs;
  const char* data_home = std::getenv("XDG_DATA_HOME");
  dirs.emplace_back(data_home != nullptr && *data_home ? fs::path(data_home) : fs::path(home()) / ".local/share");
  const char* list = std::getenv("XDG_DATA_DIRS");
  std::stringstream stream(list != nullptr && *list ? list : "/usr/local/share:/usr/share");
  for (std::string dir; std::getline(stream, dir, ':');)
    if (!dir.empty()) dirs.emplace_back(dir);
  return dirs;
}

bool on_path(const std::string& program) {
  const char* path = std::getenv("PATH");
  std::stringstream stream(path != nullptr ? path : "");
  for (std::string dir; std::getline(stream, dir, ':');)
    if (!dir.empty() && ::access((fs::path(dir) / program).c_str(), X_OK) == 0) return true;
  return false;
}

// Starts a program detached: its own session, stdio on /dev/null, and a
// double fork so the shell never holds a zombie for it.
void spawn(const std::vector<std::string>& argv) {
  if (argv.empty()) return;
  std::vector<char*> args;
  for (const std::string& arg : argv) args.push_back(const_cast<char*>(arg.c_str()));
  args.push_back(nullptr);
  const pid_t child = ::fork();
  if (child == 0) {
    ::setsid();
    if (::fork() != 0) ::_exit(0);
    const int null = ::open("/dev/null", O_RDWR);
    if (null >= 0) {
      ::dup2(null, 0);
      ::dup2(null, 1);
      ::dup2(null, 2);
    }
    ::execvp(args[0], args.data());
    ::_exit(127);
  }
  if (child > 0) ::waitpid(child, nullptr, 0);
}

// "file:///home/you/My%20file.txt"
std::string file_uri(const fs::path& path) {
  std::string uri = "file://";
  for (const unsigned char c : fs::absolute(path).string()) {
    if (std::isalnum(c) || std::string_view("/-._~").contains(static_cast<char>(c))) uri.push_back(static_cast<char>(c));
    else {
      static constexpr char hex[] = "0123456789ABCDEF";
      uri += '%';
      uri += hex[c >> 4];
      uri += hex[c & 15];
    }
  }
  return uri;
}

// --- Desktop entries ------------------------------------------------------------

std::optional<Entry> read_entry(const fs::path& path) {
  std::ifstream input(path);
  if (!input) return std::nullopt;
  Entry entry;
  bool inside = false;
  bool hidden = false;
  for (std::string line; std::getline(input, line);) {
    if (line.starts_with('[')) {
      inside = line.starts_with("[Desktop Entry]");
      continue;
    }
    const auto equals = line.find('=');
    if (!inside || equals == std::string::npos) continue;
    std::string key = line.substr(0, equals);
    while (!key.empty() && key.back() == ' ') key.pop_back();
    std::string value = line.substr(equals + 1);
    while (!value.empty() && value.front() == ' ') value.erase(value.begin());
    if (key == "Name") entry.name = value;
    else if (key == "Icon") entry.icon = value;
    else if (key == "Exec") entry.exec = value;
    else if (key == "Terminal") entry.terminal = value == "true";
    else if ((key == "Hidden" || key == "NoDisplay") && value == "true") hidden = true;
  }
  (void)hidden;  // shown anyway: the user put it on the desktop
  if (entry.name.empty()) entry.name = path.stem().string();
  return entry;
}

// An Exec line's words, field codes dropped (a launcher runs without files).
std::vector<std::string> exec_words(const std::string& line) {
  std::vector<std::string> words;
  std::string word;
  bool quoted = false;
  bool any = false;
  for (std::size_t i = 0; i < line.size(); ++i) {
    const char c = line[i];
    if (quoted && c == '\\' && i + 1 < line.size()) word.push_back(line[++i]);
    else if (c == '"') quoted = !quoted, any = true;
    else if (!quoted && (c == ' ' || c == '\t')) {
      if (any || !word.empty()) words.push_back(std::move(word));
      word.clear();
      any = false;
    } else word.push_back(c);
  }
  if (any || !word.empty()) words.push_back(std::move(word));
  std::vector<std::string> argv;
  for (const std::string& w : words) {
    if (w.size() == 2 && w[0] == '%') {
      if (w[1] == '%') argv.emplace_back("%");
      continue;
    }
    std::string expanded;
    for (std::size_t i = 0; i < w.size(); ++i) {
      if (w[i] == '%' && i + 1 < w.size()) {
        if (w[++i] == '%') expanded.push_back('%');
      } else expanded.push_back(w[i]);
    }
    argv.push_back(std::move(expanded));
  }
  return argv;
}

// --- File types (shared-mime-info) ----------------------------------------------

struct Glob {
  int weight = 50;
  std::string mime;
  std::string pattern;  // lowercased unless case_sensitive
  bool suffix = false;  // "*.ext": pattern holds ".ext"
  bool case_sensitive = false;
};

// mime/globs2 from every data dir: "weight:type:glob[:flags]".
std::vector<Glob> load_globs() {
  std::vector<Glob> globs;
  for (const fs::path& dir : data_dirs()) {
    std::ifstream input(dir / "mime/globs2");
    for (std::string line; std::getline(input, line);) {
      if (line.empty() || line[0] == '#') continue;
      std::vector<std::string> fields;
      std::stringstream stream(line);
      for (std::string field; std::getline(stream, field, ':');) fields.push_back(field);
      if (fields.size() < 3) continue;
      Glob glob;
      glob.weight = std::atoi(fields[0].c_str());
      glob.mime = fields[1];
      glob.case_sensitive = fields.size() > 3 && fields[3].contains("cs");
      const std::string& pattern = fields[2];
      if (pattern.starts_with("*.") && pattern.find_first_of("*?[", 1) == std::string::npos) {
        glob.suffix = true;
        glob.pattern = pattern.substr(1);
      } else if (pattern.find_first_of("*?[") == std::string::npos) {
        glob.pattern = pattern;  // a whole file name, like "Makefile"
      } else {
        continue;  // other wildcards are rare; the generic icon covers them
      }
      if (!glob.case_sensitive) glob.pattern = lowercase(glob.pattern);
      globs.push_back(std::move(glob));
    }
  }
  return globs;
}

std::string mime_of(const fs::path& path, const std::vector<Glob>& globs) {
  std::error_code error;
  if (fs::is_directory(path, error)) return "inode/directory";
  const std::string name = path.filename().string();
  if (name.ends_with(".desktop")) return "application/x-desktop";
  const std::string lower = lowercase(name);
  const Glob* best = nullptr;
  for (const Glob& glob : globs) {
    const std::string& subject = glob.case_sensitive ? name : lower;
    const bool match = glob.suffix ? subject.ends_with(glob.pattern) : subject == glob.pattern;
    if (!match) continue;
    if (best == nullptr || glob.weight > best->weight ||
        (glob.weight == best->weight && glob.pattern.size() > best->pattern.size()))
      best = &glob;
  }
  return best != nullptr ? best->mime : "application/octet-stream";
}

// Theme icon names, best first, and a Material Symbols fallback.
std::pair<std::vector<std::string>, std::string> look(const std::string& mime) {
  if (mime == "inode/directory") return {{"folder"}, "folder"};
  const std::string top = mime.substr(0, mime.find('/'));
  std::string dashed = mime;
  std::ranges::replace(dashed, '/', '-');
  std::vector<std::string> names{dashed};
  std::string glyph = "draft";
  static const std::map<std::string, std::string> glyphs{
      {"image", "image"}, {"video", "movie"}, {"audio", "music_note"}, {"text", "description"}, {"font", "font_download"}};
  if (mime == "application/pdf") {
    names.emplace_back("x-office-document");
    glyph = "picture_as_pdf";
  } else if (std::ranges::any_of(std::vector<std::string>{"zip", "tar", "rar", "7z", "gzip", "bzip", "xz", "zstd",
                                                          "compressed"},
                                 [&](const std::string& word) { return mime.contains(word); })) {
    names.emplace_back("package-x-generic");
    glyph = "folder_zip";
  } else if (const auto found = glyphs.find(top); found != glyphs.end()) {
    glyph = found->second;
  }
  names.push_back(top + "-x-generic");
  names.emplace_back("text-x-generic");
  return {names, glyph};
}

// mime -> app ids that open it, from every data dir's mimeinfo.cache.
std::map<std::string, std::vector<std::string>> load_handlers() {
  std::map<std::string, std::vector<std::string>> handlers;
  for (const fs::path& dir : data_dirs()) {
    std::ifstream input(dir / "applications/mimeinfo.cache");
    for (std::string line; std::getline(input, line);) {
      const auto equals = line.find('=');
      if (line.starts_with('[') || equals == std::string::npos) continue;
      auto& list = handlers[line.substr(0, equals)];
      std::stringstream stream(line.substr(equals + 1));
      for (std::string id; std::getline(stream, id, ';');)
        if (!id.empty() && std::ranges::find(list, id) == list.end()) list.push_back(id);
    }
  }
  return handlers;
}

const std::vector<std::string>& image_types() {
  static const std::vector<std::string> types{"image/png", "image/jpeg", "image/webp", "image/gif",
                                              "image/bmp", "image/svg+xml", "image/avif"};
  return types;
}

// --- The plugin -----------------------------------------------------------------

class Desktop final : public blxshell::Plugin {
 public:
  ~Desktop() override {
    stopping_ = true;
    wake();
    if (worker_.joinable()) worker_.join();
    if (wake_fd_ >= 0) ::close(wake_fd_);
  }

  void start(blxshell::Host& host) override {
    host_ = &host;
    wake_fd_ = ::eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    read_settings();
    worker_ = std::thread([this] { work(); });
  }

  void store_changed(blxshell::Host&) override {
    read_settings();
    wake();
  }

  bool command(blxshell::Host&, std::string_view name, const std::vector<std::string>&) override {
    if (name == "refresh") {
      reload_ = true;
      wake();
      return true;
    }
    if (name == "open-folder") {
      spawn({"xdg-open", folder().string()});
      return true;
    }
    return false;
  }

  void desktop_action(blxshell::Host& host, std::string_view in_area, std::string_view item,
                      std::string_view action) override {
    if (in_area != area) return;
    Detail detail;
    {
      std::lock_guard lock(mutex_);
      const auto found = details_.find(std::string(item));
      if (found == details_.end()) return;
      detail = found->second;
    }
    const std::string path = detail.path.string();
    if (action == "open") {
      spawn({"xdg-open", path});
    } else if (action == "run") {
      if (!detail.app.empty()) {
        if (!host.launch(detail.app, {})) host.log("can't start " + detail.app);
      } else if (detail.launcher) {
        std::vector<std::string> argv = exec_words(detail.launcher->exec);
        if (detail.launcher->terminal && !argv.empty()) argv.insert(argv.begin(), "xdg-terminal-exec");
        spawn(argv);
      }
    } else if (action.starts_with("with:")) {
      const std::string app(action.substr(5));
      if (!host.launch(app, {path})) host.log("can't open " + path + " with " + app);
    } else if (action == "reveal") {
      // The file manager's ShowItems, else the folder it's in.
      spawn({"sh", "-c",
             "gdbus call --session --dest org.freedesktop.FileManager1 --object-path /org/freedesktop/FileManager1 "
             "--method org.freedesktop.FileManager1.ShowItems \"['$1']\" '' >/dev/null 2>&1 || xdg-open \"$2\"",
             "sh", file_uri(detail.path), detail.path.parent_path().string()});
    } else if (action == "copy") {
      if (on_path("wl-copy")) spawn({"wl-copy", "--", path});
      else host.log("wl-copy isn't installed: can't copy");
    } else if (action == "trash") {
      trash(host, detail.path);
      wake();  // gone from the desktop now
    }
  }

 private:
  // --- Settings, read on the shell's thread from the store.

  template <class T>
  void read(const char* key, T& value) const {
    try {
      const std::string text = host_->get(key);
      if (!text.empty()) value = json::parse(text).get<T>();
    } catch (const std::exception&) {
    }
  }

  void read_settings() {
    Settings fresh;
    read("folder", fresh.folder);
    read("show_hidden", fresh.show_hidden);
    read("sort", fresh.sort);
    read("folders_first", fresh.folders_first);
    double other_apps = fresh.other_apps;
    read("other_apps", other_apps);
    fresh.other_apps = std::clamp(static_cast<int>(other_apps), 0, 8);
    read("shape", fresh.shape);
    read("tint", fresh.tint);
    if (fresh.sort != "name" && fresh.sort != "modified" && fresh.sort != "type") fresh.sort = "name";
    if (std::ranges::find(shapes, fresh.shape) == shapes.end()) fresh.shape = "none";
    if (fresh.tint != "none" && fresh.tint != "colour" && fresh.tint != "themed") fresh.tint = "none";
    std::string trimmed = fresh.folder;
    while (!trimmed.empty() && std::isspace(static_cast<unsigned char>(trimmed.back()))) trimmed.pop_back();
    while (!trimmed.empty() && std::isspace(static_cast<unsigned char>(trimmed.front()))) trimmed.erase(trimmed.begin());
    fresh.folder = trimmed;
    std::lock_guard lock(mutex_);
    settings_ = fresh;
  }

  Settings settings() const {
    std::lock_guard lock(mutex_);
    return settings_;
  }

  fs::path folder() const {
    const Settings s = settings();
    if (!s.folder.empty()) return s.folder.starts_with("~/") ? fs::path(home()) / s.folder.substr(2) : fs::path(s.folder);
    const char* config = std::getenv("XDG_CONFIG_HOME");
    std::ifstream input(fs::path(config != nullptr && *config ? config : home() + "/.config") / "user-dirs.dirs");
    for (std::string line; std::getline(input, line);) {
      if (!line.starts_with("XDG_DESKTOP_DIR=")) continue;
      std::string value = line.substr(16);
      std::erase(value, '"');
      if (value.starts_with("$HOME")) value = home() + value.substr(5);
      return value;
    }
    return fs::path(home()) / "Desktop";
  }

  void wake() const {
    if (wake_fd_ < 0) return;
    const std::uint64_t one = 1;
    const auto written = ::write(wake_fd_, &one, sizeof one);
    (void)written;
  }

  // --- The worker: scan, send, wait for a change.

  void work() {
    const int watch_fd = ::inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    int watch = -1;
    fs::path watched;
    std::string last;
    std::vector<Glob> globs = load_globs();
    auto handlers = load_handlers();
    while (!stopping_) {
      if (reload_.exchange(false)) {
        globs = load_globs();
        handlers = load_handlers();
      }
      const fs::path dir = folder();
      if (dir != watched && watch_fd >= 0) {
        if (watch >= 0) ::inotify_rm_watch(watch_fd, watch);
        watch = ::inotify_add_watch(watch_fd, dir.c_str(),
                                    IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_CLOSE_WRITE | IN_ATTRIB |
                                        IN_DELETE_SELF | IN_MOVE_SELF);
        watched = dir;
      }
      try {
        const std::string message = build(dir, globs, handlers);
        if (message != last) {
          host_->desktop(message);
          last = message;
        }
      } catch (const std::exception&) {
        // A folder mid-change: the next event tries again.
      }
      // A change in the folder, a setting, an action, or every few seconds
      // (a folder that didn't exist yet, apps installed meanwhile).
      pollfd fds[2] = {{.fd = wake_fd_, .events = POLLIN, .revents = 0}, {.fd = watch_fd, .events = POLLIN, .revents = 0}};
      ::poll(fds, watch_fd >= 0 ? 2 : 1, 5000);
      std::uint64_t count = 0;
      while (::read(wake_fd_, &count, sizeof count) > 0) {
      }
      alignas(inotify_event) char buffer[4096];
      bool changed = false;
      while (watch_fd >= 0 && ::read(watch_fd, buffer, sizeof buffer) > 0) changed = true;
      if (changed) {
        // A copy or download writes in bursts: let it settle.
        std::this_thread::sleep_for(std::chrono::milliseconds(120));
        while (::read(watch_fd, buffer, sizeof buffer) > 0) {
        }
        if (!fs::exists(watched)) watched.clear();  // re-watch once it's back
      }
    }
    if (watch_fd >= 0) ::close(watch_fd);
  }

  // The desktop message for the folder as it is now, and the details its
  // actions need.
  std::string build(const fs::path& dir, const std::vector<Glob>& globs,
                    const std::map<std::string, std::vector<std::string>>& handlers) {
    const Settings s = settings();
    std::map<std::string, App> apps;
    try {
      for (const json& entry : json::parse(host_->applications("")))
        apps.emplace(entry.value("id", ""), App{entry.value("name", ""), entry.value("icon", ""), entry.value("iconPath", "")});
    } catch (const std::exception&) {
    }

    struct Found {
      std::string name;
      fs::path path;
      std::string mime;
      fs::file_time_type modified;
      bool directory = false;
    };
    std::vector<Found> found;
    std::error_code error;
    for (const fs::directory_entry& entry : fs::directory_iterator(dir, error)) {
      const std::string name = entry.path().filename().string();
      if (name.starts_with('.') && !s.show_hidden) continue;
      std::error_code status_error;
      const auto status = fs::status(entry.path(), status_error);
      if (status_error || !fs::exists(status)) continue;  // a dangling link
      found.push_back({name, entry.path(), mime_of(entry.path(), globs), fs::last_write_time(entry.path(), status_error),
                       fs::is_directory(status)});
    }
    const auto by_name = [](const Found& a, const Found& b) { return lowercase(a.name) < lowercase(b.name); };
    if (s.sort == "modified") std::ranges::sort(found, [](const Found& a, const Found& b) { return a.modified > b.modified; });
    else if (s.sort == "type")
      std::ranges::sort(found, [&](const Found& a, const Found& b) {
        return a.mime != b.mime ? a.mime < b.mime : by_name(a, b);
      });
    else std::ranges::sort(found, by_name);
    if (s.folders_first) std::ranges::stable_partition(found, [](const Found& f) { return f.directory; });

    json items = json::array();
    std::map<std::string, Detail> details;
    for (const Found& f : found) {
      auto [icons, glyph] = look(f.mime);
      std::string label = f.name;
      std::string image;
      Detail detail{.path = f.path, .mime = f.mime, .app = {}, .launcher = {}};
      json actions = json::array();
      if (f.mime == "application/x-desktop") {
        // An installed app by its id (a link's target, else the file's own
        // name), else whatever the file says.
        std::error_code link_error;
        const fs::path target = fs::is_symlink(f.path, link_error) ? fs::read_symlink(f.path, link_error) : fs::path();
        const std::string id = (!target.empty() ? target : f.path).filename().string();
        glyph = "apps";
        if (const auto app = apps.find(id); app != apps.end()) {
          detail.app = id;
          label = app->second.name;
          // App icons go in "icon", not "image": the shell sets them on the
          // icon shape and tints them; "image" is for photos.
          icons = {app->second.icon, "application-x-executable"};
          if (!app->second.icon_path.empty()) icons.insert(icons.begin(), app->second.icon_path);
        } else if (auto entry = read_entry(f.path)) {
          label = entry->name;
          if (!entry->icon.empty()) icons = {entry->icon, "application-x-executable"};
          detail.launcher = std::move(entry);
        }
        actions.push_back({{"id", "run"}, {"label", "Run"}, {"glyph", "play_arrow"}});
      } else {
        if (std::ranges::find(image_types(), f.mime) != image_types().end()) {
          std::error_code size_error;
          if (fs::file_size(f.path, size_error) <= thumbnail_limit && !size_error) image = f.path.string();
        }
        actions.push_back({{"id", "open"}, {"label", "Open"}, {"glyph", "open_in_new"}});
        if (!f.directory) {
          int offered = 0;
          if (const auto list = handlers.find(f.mime); list != handlers.end())
            for (const std::string& id : list->second) {
              if (offered >= s.other_apps) break;
              const auto app = apps.find(id);
              if (app == apps.end()) continue;
              actions.push_back({{"id", "with:" + id}, {"label", "Open with " + app->second.name}, {"glyph", "apps"}});
              ++offered;
            }
        }
      }
      actions.push_back({{"id", "reveal"}, {"label", "Show in folder"}, {"glyph", "folder_open"}});
      actions.push_back({{"id", "copy"}, {"label", "Copy path"}, {"glyph", "content_copy"}});
      actions.push_back({{"id", "trash"}, {"label", "Move to trash"}, {"glyph", "delete"}, {"danger", true}});
      json item{{"id", f.name}, {"label", label}, {"icon", icons}, {"glyph", glyph}, {"actions", actions}};
      if (!image.empty()) item["image"] = image;
      items.push_back(std::move(item));
      details.emplace(f.name, std::move(detail));
    }
    {
      std::lock_guard lock(mutex_);
      details_ = std::move(details);
    }
    return json{{"id", area}, {"items", items}, {"style", {{"shape", s.shape}, {"tint", s.tint}}}}.dump();
  }

  // gio's trash, else the freedesktop.org trash in the home folder.
  static void trash(blxshell::Host& host, const fs::path& path) {
    if (on_path("gio")) {
      spawn({"gio", "trash", "--", path.string()});
      return;
    }
    const char* data_home = std::getenv("XDG_DATA_HOME");
    const fs::path base = fs::path(data_home != nullptr && *data_home ? data_home : home() + "/.local/share") / "Trash";
    std::error_code error;
    fs::create_directories(base / "files", error);
    fs::create_directories(base / "info", error);
    const std::string original = path.filename().string();
    std::string name = original;
    for (int counter = 2; fs::exists(base / "files" / name) || fs::exists(base / "info" / (name + ".trashinfo")); ++counter) {
      const auto dot = original.find('.', 1);
      name = dot == std::string::npos ? std::format("{}.{}", original, counter)
                                      : std::format("{}.{}{}", original.substr(0, dot), counter, original.substr(dot));
    }
    char stamp[32];
    const std::time_t now = std::time(nullptr);
    std::strftime(stamp, sizeof stamp, "%Y-%m-%dT%H:%M:%S", std::localtime(&now));
    std::ofstream(base / "info" / (name + ".trashinfo"))
        << "[Trash Info]\nPath=" << file_uri(path).substr(7) << "\nDeletionDate=" << stamp << '\n';
    fs::rename(path, base / "files" / name, error);
    if (error) {
      fs::remove(base / "info" / (name + ".trashinfo"), error);
      host.log("can't move " + path.string() + " to the trash: " + error.message());
    }
  }

  blxshell::Host* host_ = nullptr;
  mutable std::mutex mutex_;
  Settings settings_;
  std::map<std::string, Detail> details_;
  std::thread worker_;
  int wake_fd_ = -1;
  std::atomic<bool> stopping_ = false;
  std::atomic<bool> reload_ = false;
};

}  // namespace

BLXSHELL_PLUGIN(Desktop)
