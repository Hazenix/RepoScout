import AppKit

guard CommandLine.arguments.count == 2 else {
    fputs("usage: make-icon OUTPUT.png\n", stderr)
    exit(2)
}

let size = NSSize(width: 1024, height: 1024)
let image = NSImage(size: size)
image.lockFocus()

let tile = NSBezierPath(roundedRect: NSRect(origin: .zero, size: size), xRadius: 225, yRadius: 225)
NSColor(calibratedRed: 0.969, green: 0.961, blue: 0.937, alpha: 1).setFill()
tile.fill()

let ring = NSBezierPath(ovalIn: NSRect(x: 232, y: 232, width: 560, height: 560))
ring.lineWidth = 66
NSColor(calibratedRed: 0.125, green: 0.302, blue: 0.239, alpha: 1).setStroke()
ring.stroke()

let slash = NSBezierPath()
slash.move(to: NSPoint(x: 300, y: 258))
slash.line(to: NSPoint(x: 724, y: 766))
slash.lineWidth = 72
slash.lineCapStyle = .round
NSColor(calibratedRed: 0.639, green: 0.282, blue: 0.165, alpha: 1).setStroke()
slash.stroke()

image.unlockFocus()
guard let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("could not render icon\n", stderr)
    exit(1)
}
try png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
