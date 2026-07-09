import SwiftUI

// Rewisp visual system — graphite base, indigo→violet wisp accent (matches the
// app icon), soft cards, springs everywhere.
enum Theme {
    static let accent = Color(red: 0.56, green: 0.64, blue: 1.0)      // #8EA2FF
    static let accent2 = Color(red: 0.69, green: 0.55, blue: 1.0)     // #B08CFF
    static let wisp = LinearGradient(colors: [accent, accent2],
                                     startPoint: .topLeading, endPoint: .bottomTrailing)
    static let spring = Animation.spring(response: 0.35, dampingFraction: 0.8)
}

// Soft rounded card used across the main window.
struct Card<Content: View>: View {
    var pad: CGFloat = 18
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(pad)
            .background(.quaternary.opacity(0.28),
                        in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(.white.opacity(0.06)))
    }
}

// Section label with a tinted icon chip.
struct CardHeader: View {
    let title: String
    let symbol: String
    var trailing: String? = nil
    var body: some View {
        HStack(spacing: 10) {
            IconChip(symbol: symbol, size: 26)
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            Spacer()
            if let trailing {
                Text(trailing)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.tertiary)
            }
        }
    }
}

// Large tab header: big rounded title + quiet subtitle.
struct TabHeader: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 30, weight: .bold, design: .rounded))
            Text(subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// Horizontal capsule bar for time reports.
struct TimeBar: View {
    let label: String
    let minutes: Int
    let maxMinutes: Int
    var body: some View {
        HStack(spacing: 10) {
            Text(label)
                .font(.caption.weight(.medium))
                .frame(width: 120, alignment: .leading)
                .lineLimit(1)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(.quaternary.opacity(0.4))
                    Capsule()
                        .fill(Theme.wisp)
                        .frame(width: max(geo.size.width * CGFloat(minutes) / CGFloat(max(maxMinutes, 1)), 5))
                }
            }
            .frame(height: 7)
            Text(minutes >= 60 ? String(format: "%dh %02dm", minutes / 60, minutes % 60) : "\(minutes)m")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 56, alignment: .trailing)
        }
    }
}

// Landing-page-style icon chip: tinted rounded square with a gradient glyph.
struct IconChip: View {
    let symbol: String
    var size: CGFloat = 34
    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
            .fill(Theme.accent.opacity(0.10))
            .overlay(RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
                .strokeBorder(Theme.accent.opacity(0.22)))
            .frame(width: size, height: size)
            .overlay(
                Image(systemName: symbol)
                    .font(.system(size: size * 0.46, weight: .semibold))
                    .foregroundStyle(Theme.wisp)
                    .symbolRenderingMode(.hierarchical)
            )
    }
}

// Big number + label, used in the Today hero strip.
struct StatTile: View {
    let value: String
    let label: String
    var accent: Bool = false
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundStyle(accent ? AnyShapeStyle(Theme.wisp) : AnyShapeStyle(.primary))
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// Hover-reactive style for plain icon buttons.
struct HoverButton: ButtonStyle {
    @State private var hovering = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(6)
            .background(hovering ? AnyShapeStyle(.quaternary.opacity(0.5)) : AnyShapeStyle(.clear),
                        in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
            .onHover { hovering = $0 }
    }
}
