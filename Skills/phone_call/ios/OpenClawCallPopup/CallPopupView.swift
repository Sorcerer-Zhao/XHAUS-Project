import SwiftUI

/// Exact popup layout: script on top, Cancel (gray) / Call (green) below.
/// Open via URL: openclawcall://popup?script=...&tel=tel:+86138...
struct CallPopupView: View {
    let script: String
    let tel: String
    var onCancel: () -> Void
    var onCall: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                Text(script)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(20)
            }
            .frame(maxHeight: .infinity)

            HStack(spacing: 12) {
                Button(action: onCancel) {
                    Text("Cancel")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                }
                .background(Color(.systemGray4))
                .foregroundStyle(.primary)
                .clipShape(RoundedRectangle(cornerRadius: 12))

                Button(action: onCall) {
                    Text("Call")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                }
                .background(Color.green)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .padding(16)
        }
        .background(Color(.systemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .shadow(radius: 20)
        .padding(24)
    }
}

#Preview {
    ZStack {
        Color.black.opacity(0.4).ignoresSafeArea()
        CallPopupView(
            script: "你好，我想预订今晚六点，四位，姓张。",
            tel: "tel:+8613800138000",
            onCancel: {},
            onCall: {}
        )
    }
}
