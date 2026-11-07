// vt-tunnel-config — console configurator for the vt-tunnel daemon.
//
// Minimal shell: one empty bordered window titled "vt-tunnel config",
// full-screen. Quit on q, Escape or Ctrl-C. No widgets or config access yet.

#include <ftxui/component/component.hpp>  // for Renderer, CatchEvent
#include <ftxui/component/event.hpp>      // for Event
#include <ftxui/component/screen_interactive.hpp>  // for ScreenInteractive
#include <ftxui/dom/elements.hpp>  // for window, text, emptyElement, flex

using namespace ftxui;

int main() {
  auto screen = ScreenInteractive::Fullscreen();

  auto renderer = Renderer([] {
    return window(text("vt-tunnel config"), emptyElement()) | flex;
  });

  auto app = CatchEvent(renderer, [&](const Event& event) {
    if (event == Event::Character('q') ||  //
        event == Event::Escape ||          //
        event == Event::CtrlC) {
      screen.ExitLoopClosure()();
      return true;
    }
    return false;
  });

  // Handle Ctrl-C ourselves so a caught Event::CtrlC exits cleanly with
  // status 0 instead of FTXUI's record-SIGINT-and-re-raise path (130).
  screen.ForceHandleCtrlC(false);

  screen.Loop(app);
  return 0;
}
