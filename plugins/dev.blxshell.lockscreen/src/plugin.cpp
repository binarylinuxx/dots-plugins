// Lock screen widgets: lib/plugin.so draws five views the user places on the
// lock screen with blxshell's layout editor (`blxshell lockscreen edit`, Add):
//
//   LockGreeting   "Good evening, Alex", and a line under it
//   LockMessage    a card with an icon, a title and a message ("If found…")
//   LockCalendar   this month, today marked
//   LockCountdown  days until (or since) a date
//   LockSystem     host name, uptime and kernel
//
// Each draws at the scale the user gave it (Host::context). On the lock screen
// they are shown only, never clicked. plugin.facet is the settings page; the
// store keys are listed there.
#include <blxshell/plugin.hpp>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdlib>
#include <ctime>
#include <format>
#include <optional>
#include <pwd.h>
#include <string>
#include <sys/sysinfo.h>
#include <sys/utsname.h>
#include <unistd.h>
#include <vector>

namespace {

using nlohmann::json;

json parse(std::string_view text) {
  if (text.empty()) return nullptr;
  json value = json::parse(text, nullptr, false);
  return value.is_discarded() ? json(nullptr) : value;
}

std::string text_of(const blxshell::Host& host, std::string_view key, std::string fallback = {}) {
  const json value = parse(host.get(key));
  return value.is_string() ? value.get<std::string>() : fallback;
}

bool flag_of(const blxshell::Host& host, std::string_view key, bool fallback) {
  const json value = parse(host.get(key));
  return value.is_boolean() ? value.get<bool>() : fallback;
}

// The size the user gave the widget in the layout editor.
float scale_of(const blxshell::Host& host) {
  const json context = parse(host.context());
  if (context.is_object() && context.contains("lock") && context["lock"].contains("scale") &&
      context["lock"]["scale"].is_number())
    return std::clamp(context["lock"]["scale"].get<float>(), 0.2F, 5.0F);
  return 1;
}

// The backdrop's opacity the user set in the layout editor (100% solid), or
// this widget's own when automatic.
float backdrop(const blxshell::Host& host, float base) {
  const json context = parse(host.context());
  if (context.is_object() && context.contains("lock") && context["lock"].contains("background") &&
      context["lock"]["background"].is_number()) {
    const float set = context["lock"]["background"].get<float>();
    if (set >= 0) return std::min(set, 1.0F);
  }
  return base;
}

// The backdrop colour the user picked for this widget or the lock screen;
// the theme's surface colour when none.
vw::Color backdrop_tint(const blxshell::Host& host) {
  const json context = parse(host.context());
  if (context.is_object() && context.contains("lock") && context["lock"].contains("backdropColour")) {
    const json& rgb = context["lock"]["backdropColour"];
    if (rgb.is_array() && rgb.size() == 3 && rgb[0].is_number())
      return vw::Color{rgb[0].get<float>(), rgb[1].get<float>(), rgb[2].get<float>(), 1.0F};
  }
  return host.colour("surfaceContainerHigh");
}

bool editing(const blxshell::Host& host) {
  const json context = parse(host.context());
  return context.is_object() && context.contains("lock") && context["lock"].value("editing", false);
}

vw::Color alpha(vw::Color colour, float a) {
  colour[3] = a;
  return colour;
}

std::tm local_now() {
  const std::time_t now = std::time(nullptr);
  std::tm local{};
  localtime_r(&now, &local);
  return local;
}

// The user's first name: the store's, else from their account's full name,
// else their login.
std::string first_name(const blxshell::Host& host) {
  if (std::string name = text_of(host, "name"); !name.empty()) return name;
  if (const passwd* account = getpwuid(getuid()); account != nullptr) {
    std::string full = account->pw_gecos != nullptr ? account->pw_gecos : "";
    full = full.substr(0, full.find(','));
    full = full.substr(0, full.find(' '));
    if (!full.empty()) return full;
    if (account->pw_name != nullptr) return account->pw_name;
  }
  const char* user = std::getenv("USER");
  return user != nullptr ? user : "";
}

// --- Drawing ------------------------------------------------------------------------

struct Text {
  std::string font;
  float size = 16;
  int weight = vw::weight::regular;
  vw::Color colour;
  float max_width = 0;
};

vw::Widget label(vw::Ui& ui, const std::string& text, const Text& style) {
  return ui.text({.text = text, .font = style.font, .size = style.size, .weight = style.weight, .color = style.colour,
                  .max_width = style.max_width});
}

vw::Widget glyph(vw::Ui& ui, const blxshell::Host& host, const std::string& name, float size, vw::Color colour) {
  return ui.text({.text = name, .font = host.font("icon"), .size = size, .color = colour});
}

// The lock screen's material (a plugin's shader, e.g. Glassify's glass), when
// one is installed: the cards are drawn in it like the shell's own.
struct Material {
  std::string shader;
  std::array<float, 4> params{};
};

std::optional<Material> material_of(const blxshell::Host& host) {
  const json context = parse(host.context());
  if (!context.is_object() || !context.contains("lock") || !context["lock"].contains("material")) return std::nullopt;
  const json& given = context["lock"]["material"];
  if (!given.is_object() || !given.value("shader", json()).is_string()) return std::nullopt;
  Material material{given["shader"].get<std::string>(), {0, 0, 0, 1}};
  if (given.contains("params") && given["params"].is_array())
    for (std::size_t index = 0; index < 3 && index < given["params"].size(); ++index)
      if (given["params"][index].is_number()) material.params[index] = given["params"][index].get<float>();
  return material;
}

// A rounded background sized to its content, built first so it sits under
// it; in the lock material when `host` has one.
template <class Content>
vw::Widget card(vw::Ui& ui, vw::Color colour, float radius, float padding, Content content,
                const blxshell::Host* host = nullptr) {
  vw::RectangleProps props{.width = 1, .height = 1, .color = colour};
  if (host != nullptr)
    if (const auto material = material_of(*host)) {
      props.shader = material->shader;
      props.shader_params = material->params;
    }
  const vw::Widget back = ui.rectangle(props);
  const vw::Widget inside = content();
  const vw::Widget body = ui.row({inside}, {.padding = padding});
  auto& rectangle = ui.scene().rectangles[back.begin];
  rectangle.width = body.width;
  rectangle.height = body.height;
  rectangle.radius = std::min(radius, body.height / 2);
  vw::Widget sized = back;
  sized.width = body.width;
  sized.height = body.height;
  return ui.stack({sized, body}, {.width = body.width, .height = body.height});
}

vw::Color role(const blxshell::Host& host, const std::string& name, const char* fallback) {
  static const std::vector<std::string> known{"text", "primary", "secondary", "tertiary", "textMuted"};
  return host.colour(std::ranges::find(known, name) != known.end() ? name : fallback);
}

// --- The views --------------------------------------------------------------------

vw::Widget greeting(vw::Ui& ui, blxshell::Host& host) {
  const float k = scale_of(host);
  const int hour = local_now().tm_hour;
  const char* phrase = hour >= 5 && hour < 12    ? "Good morning"
                       : hour >= 12 && hour < 18 ? "Good afternoon"
                       : hour >= 18 && hour < 22 ? "Good evening"
                                                 : "Good night";
  std::string line = phrase;
  if (flag_of(host, "greeting_name", true))
    if (const std::string name = first_name(host); !name.empty()) line += ", " + name;
  const vw::Widget title = label(ui, line, {.font = host.font("display"), .size = 34 * k, .weight = vw::weight::semibold,
                                            .colour = role(host, text_of(host, "greeting_colour", "text"), "text")});
  const std::string under = text_of(host, "greeting_line");
  if (under.empty()) return title;
  const vw::Widget sub = label(ui, under, {.font = host.font("text"), .size = 16 * k, .weight = vw::weight::medium,
                                           .colour = host.colour("textMuted")});
  return ui.column({title, sub}, {.gap = 6 * k, .align = vw::Align::center});
}

vw::Widget message(vw::Ui& ui, blxshell::Host& host) {
  const float k = scale_of(host);
  std::string title = text_of(host, "message_title");
  std::string body = text_of(host, "message_body");
  if (title.empty() && body.empty()) {
    if (!editing(host)) return {};
    title = "Your message";
    body = "Write it in Settings → Plugins → Lock screen widgets";
  }
  const std::string icon = text_of(host, "message_glyph", "info");
  return card(ui, alpha(backdrop_tint(host), backdrop(host, 0.88F)), 26 * k, 18 * k, [&] {
    // vw lays out in build order: the badge first, then the words.
    const vw::Widget badge = card(ui, host.colour("primaryContainer"), 20 * k, 9 * k,
                                  [&] { return glyph(ui, host, icon, 22 * k, host.colour("primary")); });
    std::vector<vw::Widget> lines;
    if (!title.empty())
      lines.push_back(label(ui, title, {.font = host.font("display"), .size = 17 * k, .weight = vw::weight::semibold,
                                        .colour = host.colour("text"), .max_width = 380 * k}));
    if (!body.empty())
      lines.push_back(label(ui, body, {.font = host.font("text"), .size = 14 * k, .colour = host.colour("textMuted"),
                                       .max_width = 380 * k}));
    const vw::Widget text = ui.column(lines, {.gap = 4 * k, .align = vw::Align::start});
    return ui.row({badge, text}, {.gap = 14 * k, .align = vw::Align::center});
  }, &host);
}

int days_in(int year, int month) {  // month 0-11
  static constexpr int days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  const bool leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
  return month == 1 && leap ? 29 : days[month];
}

vw::Widget calendar(vw::Ui& ui, blxshell::Host& host) {
  const float k = scale_of(host);
  const std::tm today = local_now();
  const bool monday = text_of(host, "week_start", "monday") != "sunday";
  const int year = today.tm_year + 1900;
  const int month = today.tm_mon;
  // Weekday of the 1st: from today's, back over the days before it.
  const int first = ((today.tm_wday - (today.tm_mday - 1)) % 7 + 7) % 7;  // 0 Sunday
  const int offset = monday ? (first + 6) % 7 : first;
  const int length = days_in(year, month);
  const float cell = 34 * k;

  static constexpr const char* months[] = {"January", "February", "March",     "April",   "May",      "June",
                                           "July",    "August",   "September", "October", "November", "December"};
  const auto centred = [&](vw::Widget inside) {
    return ui.row({inside}, {.width = cell, .height = cell, .justify = vw::Justify::center, .align = vw::Align::center});
  };
  return card(ui, alpha(backdrop_tint(host), backdrop(host, 0.88F)), 28 * k, 16 * k, [&] {
    std::vector<vw::Widget> rows;
    rows.push_back(label(ui, std::format("{} {}", months[month], year),
                         {.font = host.font("display"), .size = 16 * k, .weight = vw::weight::semibold,
                          .colour = host.colour("primary")}));
    std::vector<vw::Widget> header;
    const std::string names = monday ? "MTWTFSS" : "SMTWTFS";
    for (const char letter : names)
      header.push_back(centred(label(ui, std::string(1, letter), {.font = host.font("text"), .size = 12 * k,
                                                                  .weight = vw::weight::semibold,
                                                                  .colour = host.colour("textMuted")})));
    rows.push_back(ui.row(header, {.gap = 2 * k}));
    for (int start = -offset; start < length; start += 7) {
      std::vector<vw::Widget> week;
      for (int index = start; index < start + 7; ++index) {
        const int day = index + 1;
        if (day < 1 || day > length) {
          week.push_back(ui.rectangle({.width = cell, .height = cell, .color = alpha(host.colour("surface"), 0)}));
          continue;
        }
        const bool now = day == today.tm_mday;
        const Text style{.font = host.font("text"), .size = 13 * k, .weight = now ? vw::weight::bold : vw::weight::medium,
                         .colour = now ? host.colour("primaryText") : host.colour("text")};
        if (!now) {
          week.push_back(centred(label(ui, std::to_string(day), style)));
          continue;
        }
        // Today: on a disc, built before the number so it sits under it.
        const vw::Widget disc = ui.rectangle({.width = cell, .height = cell, .radius = cell / 2, .color = host.colour("primary")});
        week.push_back(ui.stack({disc, centred(label(ui, std::to_string(day), style))}, {.width = cell, .height = cell}));
      }
      rows.push_back(ui.row(week, {.gap = 2 * k}));
    }
    return ui.column(rows, {.gap = 4 * k, .align = vw::Align::start});
  }, &host);
}

// Days from today to YYYY-MM-DD, local time; nullopt when it isn't a date.
std::optional<int> days_until(const std::string& date) {
  int year = 0;
  unsigned month = 0;
  unsigned day = 0;
  if (std::sscanf(date.c_str(), "%d-%u-%u", &year, &month, &day) != 3) return std::nullopt;
  const std::chrono::year_month_day target{std::chrono::year{year}, std::chrono::month{month}, std::chrono::day{day}};
  if (!target.ok()) return std::nullopt;
  const std::tm now = local_now();
  const std::chrono::year_month_day today{std::chrono::year{now.tm_year + 1900},
                                          std::chrono::month{static_cast<unsigned>(now.tm_mon + 1)},
                                          std::chrono::day{static_cast<unsigned>(now.tm_mday)}};
  return static_cast<int>((std::chrono::sys_days{target} - std::chrono::sys_days{today}).count());
}

vw::Widget countdown(vw::Ui& ui, blxshell::Host& host) {
  const float k = scale_of(host);
  std::string event = text_of(host, "countdown_label");
  std::optional<int> days = days_until(text_of(host, "countdown_date"));
  if (!days) {
    if (!editing(host)) return {};
    // Something to place until it is set: the next New Year.
    days = days_until(std::format("{}-01-01", local_now().tm_year + 1901));
    event = "New Year";
  }
  if (event.empty()) event = "the day";
  const int count = std::abs(*days);
  const std::string number = *days == 0 ? "Today" : std::to_string(count);
  const std::string words = *days == 0 ? event
                            : *days > 0 ? std::format("{} until {}", count == 1 ? "day" : "days", event)
                                        : std::format("{} since {}", count == 1 ? "day" : "days", event);
  return card(ui, alpha(backdrop_tint(host), backdrop(host, 0.88F)), 26 * k, 16 * k, [&] {
    const vw::Widget big = label(ui, number, {.font = host.font("display"), .size = 40 * k, .weight = vw::weight::black,
                                              .colour = host.colour("primary")});
    const vw::Widget small = label(ui, words, {.font = host.font("text"), .size = 14 * k, .weight = vw::weight::medium,
                                               .colour = host.colour("text"), .max_width = 260 * k});
    return ui.row({big, small}, {.gap = 14 * k, .align = vw::Align::center});
  }, &host);
}

std::string uptime() {
  struct sysinfo info {};
  if (sysinfo(&info) != 0) return {};
  const long minutes = info.uptime / 60;
  if (minutes < 60) return std::format("up {} min", minutes);
  if (minutes < 60 * 24) return std::format("up {} h {} min", minutes / 60, minutes % 60);
  return std::format("up {} d {} h", minutes / (60 * 24), minutes / 60 % 24);
}

vw::Widget system_line(vw::Ui& ui, blxshell::Host& host) {
  const float k = scale_of(host);
  utsname names{};
  uname(&names);
  struct Part {
    std::string glyph;
    std::string text;
  };
  std::vector<Part> parts{{"computer", names.nodename}};
  if (flag_of(host, "system_uptime", true)) parts.push_back({"schedule", uptime()});
  if (flag_of(host, "system_kernel", false)) parts.push_back({"memory", names.release});
  return card(ui, alpha(backdrop_tint(host), backdrop(host, 0.78F)), 22 * k, 11 * k, [&] {
    std::vector<vw::Widget> items;
    for (const Part& part : parts) {
      if (part.text.empty()) continue;
      items.push_back(glyph(ui, host, part.glyph, 18 * k, host.colour("primary")));
      items.push_back(label(ui, part.text, {.font = host.font("text"), .size = 14 * k, .weight = vw::weight::medium,
                                            .colour = host.colour("text")}));
    }
    return ui.row(items, {.gap = 8 * k, .padding = 4 * k, .align = vw::Align::center});
  }, &host);
}

class LockWidgets : public blxshell::Plugin {
 public:
  std::vector<std::string> views() const override {
    return {"LockGreeting", "LockMessage", "LockCalendar", "LockCountdown", "LockSystem"};
  }

  vw::Widget view(vw::Ui& ui, std::string_view name, blxshell::Host& host) override {
    // Everything here changes by the minute at most.
    host.refresh(30'000);
    if (name == "LockGreeting") return greeting(ui, host);
    if (name == "LockMessage") return message(ui, host);
    if (name == "LockCalendar") return calendar(ui, host);
    if (name == "LockCountdown") return countdown(ui, host);
    if (name == "LockSystem") return system_line(ui, host);
    return {};
  }
};

}  // namespace

BLXSHELL_PLUGIN(LockWidgets)
