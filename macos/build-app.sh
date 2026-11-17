#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h:h}"
app_dir="${1:-$project_dir/dist/RepoScout.app}"
build_dir="$project_dir/.build/macos"

if [[ -e "$app_dir" ]]; then
  existing_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app_dir/Contents/Info.plist" 2>/dev/null || true)
  if [[ "$existing_id" != "dev.hazenix.reposcout" ]]; then
    print -u2 "Target is not a RepoScout build: $app_dir"
    exit 1
  fi
fi

mkdir -p "$build_dir" "$app_dir/Contents/MacOS" "$app_dir/Contents/Resources"
swift build --package-path "$project_dir" --scratch-path "$build_dir/swiftpm" \
  -c release --triple arm64-apple-macosx14.0 --product RepoScout
binary_dir=$(swift build --package-path "$project_dir" --scratch-path "$build_dir/swiftpm" \
  -c release --triple arm64-apple-macosx14.0 --show-bin-path)
cp "$binary_dir/RepoScout" "$app_dir/Contents/MacOS/RepoScout"
cp "$project_dir/macos/Info.plist" "$app_dir/Contents/Info.plist"

swiftc "$project_dir/macos/MakeIcon.swift" -o "$build_dir/make-icon"
"$build_dir/make-icon" "$build_dir/icon-1024.png"
iconset="$build_dir/RepoScout.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  sips -s format png -z "$size" "$size" "$build_dir/icon-1024.png" \
    --out "$iconset/icon_${size}x${size}.png" >/dev/null
  doubled=$((size * 2))
  sips -s format png -z "$doubled" "$doubled" "$build_dir/icon-1024.png" \
    --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$app_dir/Contents/Resources/RepoScout.icns"
codesign --force --sign - "$app_dir" >/dev/null
print "$app_dir"
