import SwiftUI

// Launch choreography. A wisp strokes itself in over a blooming glow, then the
// curtain lifts to reveal the app. Used full-scale for the main window and as
// a quick content reveal for the menu bar popover.

// The wisp mark, but its stroke draws on and its glow breathes — driven by an
// external 0→1 progress so a parent can choreograph it.
struct AnimatedWisp: View {
    var progress: CGFloat          // stroke draw + dot
    var glow: CGFloat = 1          // glow intensity
    var body: some View {
        ZStack {
            // blooming glow
            Circle()
                .fill(Theme.wisp)
                .blur(radius: 26)
                .opacity(0.55 * glow)
                .scaleEffect(0.7 + 0.5 * glow)

            RoundedRectangle(cornerRadius: 15, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.16, green: 0.18, blue: 0.25),
                                              Color(red: 0.05, green: 0.06, blue: 0.11)],
                                     startPoint: .top, endPoint: .bottom))
                .overlay(RoundedRectangle(cornerRadius: 15, style: .continuous)
                    .strokeBorder(.white.opacity(0.08)))

            WispPath()
                .trim(from: 0, to: progress)
                .stroke(LinearGradient(colors: [.white, Color(red: 0.72, green: 0.78, blue: 1)],
                                       startPoint: .leading, endPoint: .trailing),
                        style: StrokeStyle(lineWidth: 3.4, lineCap: .round, lineJoin: .round))
                .padding(14)
                .shadow(color: Theme.accent.opacity(0.9), radius: 6 * progress)

            Circle().fill(.white)
                .frame(width: 7, height: 7)
                .offset(x: 17, y: -6)
                .scaleEffect(progress > 0.85 ? 1 : 0)
                .opacity(progress > 0.85 ? 1 : 0)
        }
    }
}

// Full-window splash: plays once, then lifts to reveal `content`.
struct LaunchReveal<Content: View>: View {
    @ViewBuilder var content: Content
    @State private var draw: CGFloat = 0
    @State private var glow: CGFloat = 0
    @State private var lift = false        // curtain gone
    @State private var contentIn = false   // app revealed

    var body: some View {
        ZStack {
            content
                .opacity(contentIn ? 1 : 0)
                .scaleEffect(contentIn ? 1 : 1.03)
                .blur(radius: contentIn ? 0 : 10)

            if !lift {
                ZStack {
                    Color(red: 0.043, green: 0.051, blue: 0.086)   // #0b0d16
                    RadialGradient(colors: [Theme.accent.opacity(0.16 * glow), .clear],
                                   center: .center, startRadius: 0, endRadius: 320)
                    AnimatedWisp(progress: draw, glow: glow)
                        .frame(width: 96, height: 96)
                        .scaleEffect(0.6 + 0.4 * glow)
                }
                .ignoresSafeArea()
                .transition(.opacity)
            }
        }
        .task { await play() }
        .onReceive(NotificationCenter.default.publisher(for: .rewispMainShown)) { _ in
            // Window is reused across opens; replay the splash each time.
            draw = 0; glow = 0; lift = false; contentIn = false
            Task { await play() }
        }
    }

    private func play() async {
        withAnimation(.easeOut(duration: 0.35)) { glow = 1 }
        withAnimation(.easeInOut(duration: 0.75)) { draw = 1 }
        try? await Task.sleep(for: .milliseconds(820))
        withAnimation(.easeIn(duration: 0.25)) { glow = 0 }
        withAnimation(.spring(response: 0.5, dampingFraction: 0.82)) { contentIn = true }
        withAnimation(.easeOut(duration: 0.4)) { lift = true }
    }
}

// Lightweight reveal for the popover: content springs up from a blurred,
// slightly-scaled start. Fancy but fast enough to open a hundred times a day.
struct PopoverReveal: ViewModifier {
    @State private var shown = false
    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .scaleEffect(shown ? 1 : 0.96, anchor: .top)
            .blur(radius: shown ? 0 : 6)
            .onAppear {
                shown = false
                withAnimation(.spring(response: 0.42, dampingFraction: 0.78)) { shown = true }
            }
    }
}

extension View {
    func popoverReveal() -> some View { modifier(PopoverReveal()) }
}
