# HyperX Allow Elite

The HyperX Alloy Elite keyboard enumerates on USB at 0951:16BE and has three interfaces.  The keyboard uses HID packets that are 264 bytes long.  The protocol looks similar to the Poseidon Z RGB though not identical.

## **Switch profile**

NGENUITY sends both of these packets:

| Byte Index | Description       |
| ---------- | ----------------- |
| 0x00       | 0x07              |
| 0x01       | 0x81              |
| 0x02       | Profile to select |

| Byte Index | Description       |
| ---------- | ----------------- |
| 0x00       | 0x07              |
| 0x01       | 0x01              |
| 0x02       | Profile to select |
| 0x03       | 0x00              |
| 0x04       | 0x00              |
| 0x05       | 0x00              |
| 0x06       | Brightness (0-3)  |
| 0x07       | 0x01              |

## **Set effect**

This packet is incomplete

| Byte Index | Description                                                                    |
|------------|--------------------------------------------------------------------------------|
| 0x00       | 0x07                                                                           |
| 0x01       | 0x02                                                                           |
| 0x02       | Profile to select                                                              |
| 0x03       | 0x00                                                                           |
| 0x04       |                                                                                |
| 0x05       |                                                                                |
| 0x06       |                                                                                |
| 0x07       |                                                                                |
| 0x08       |                                                                                |
| 0x09       | 0x01                                                                           |
| 0x0A       | Mode                                                                           |
| 0x0B       |                                                                                |
| 0x0C       |                                                                                |
| 0x0D       | Direction (0: Right 1: Left 2: Up 3: Down 4: In 5: Out )                       |
| 0x0E       | Direction                                                                      |
| 0x0F       |                                                                                |
| 0x10       |                                                                                |
| 0x11       |                                                                                |
| 0x12       |                                                                                |
| 0x13       |                                                                                |
| 0x14       |                                                                                |
| 0x15       |                                                                                |
| 0x16       |                                                                                |
| 0x17       |                                                                                |
| 0x18       |                                                                                |
| 0x19       |                                                                                |
| 0x1A       |                                                                                |
| 0x1B       | Reactive Mode - 0xFF: None, 0x03: Trigger, 0x04: Explosion, 0x05: HyperX Flame |
| 0x1C       | Reactive Mode                                                                  |
| 0x1D       | Reactive Mode                                                                  |
| 0x1E       | Reactive Mode                                                                  |
| 0x1F       | Reactive Mode                                                                  |
| 0x20       | Reactive Mode                                                                  |
| 0x21       | Reactive Mode                                                                  |
| 0x22       | Reactive Mode                                                                  |
| 0x23       | 24 bytes of red gradient, Index 6 for Single, Index 7 and 8 for Dual           |
| 0x3B       | 24 bytes of green gradient, Index 6 for Single, Index 7 and 8 for Dual         |
| 0x53       | 24 bytes of blue gradient, Index 6 for Single, Index 7 and 8 for Dual          |
| 0x6B       |                                                                                |
| 0x6C       |                                                                                |
| 0x6D       |                                                                                |
| 0x6E       |                                                                                |
| 0x6F       |                                                                                |
| 0x70       |                                                                                |
| 0x71       | Speed (1: Fastest - 9: Slowest)                                                |
| 0x72       |                                                                                |
| 0x73       | Color Mode - 0: Single Color 1: Dual Color, 2: Spectrum                        |
| 0x74       | Color Mode                                                                     |
| 0x75       | Color Mode                                                                     |
| 0x76       | Color Mode                                                                     |
| 0x77       | Color Mode                                                                     |
| 0x78       | Color Mode                                                                     |
| 0x79       | Color Mode                                                                     |
| 0x7A       | Color Mode                                                                     |

| Mode Value | Mode Description |
| ---------- | ---------------- |
| 0x00       | Wave             |
| 0x01       | Static           |
| 0x02       | Breathing        |

## **Color packet (Main keyboard block)**

The color channels 1-3 provide color data for the main keyboard block.  The RGB strip and media keys are not covered in these packets.

| Byte Index | Description                               |
| ---------- | ----------------------------------------- |
| 0x00       | 0x07                                      |
| 0x01       | 0x06                                      |
| 0x02       | Profile to edit                           |
| 0x03       | Color channel (1: Red, 2: Green, 3: Blue) |
| 0x04       | 0x00                                      |
| 0x05       | 0x00                                      |
| 0x06       | 0x00                                      |
| 0x07       | 0x00                                      |
| 0x08       | Key: Escape                               |
| 0x09       | Key: `/~                                  |
| 0x0A       | Key: Tab                                  |
| 0x0B       | Key: Caps Lock                            |
| 0x0C       | Key: Left Shift                           |
| 0x0D       | Key: Left Control                         |
| 0x0E       | Key: F12                                  |
| 0x0F       | Key: =/+                                  |
| 0x10       | Key: F9                                   |
| 0x11       | Key: 9                                    |
| 0x12       | Key: O                                    |
| 0x13       | Key: L                                    |
| 0x14       | Key: ,/<                                  |
| 0x15       | Key: Context                              |
| 0x16       |                                           |
| 0x17       | Key: Left Arrow                           |
| 0x18       | Key: F1                                   |
| 0x19       | Key: 1                                    |
| 0x1A       | Key: Q                                    |
| 0x1B       | Key: A                                    |
| 0x1C       |                                           |
| 0x1D       | Key: Left Windows                         |
| 0x1E       | Key: Print Screen                         |
| 0x1F       |                                           |
| 0x20       | Key: F10                                  |
| 0x21       | Key: 0                                    |
| 0x22       | Key: P                                    |
| 0x23       | Key: ;/:                                  |
| 0x24       | Key: ./>                                  |
| 0x25       |                                           |
| 0x26       | Key: Enter                                |
| 0x27       | Key: Down Arrow                           |
| 0x28       | Key: F2                                   |
| 0x29       | Key: 2                                    |
| 0x2A       | Key: W                                    |
| 0x2B       | Key: S                                    |
| 0x2C       | Key: Z                                    |
| 0x2D       | Key: Left Alt                             |
| 0x2E       | Key: Scroll Lock                          |
| 0x2F       | Key: Backspace                            |
| 0x30       | Key: F11                                  |
| 0x31       | Key: -/_                                  |
| 0x32       | Key: [/{                                  |
| 0x33       | Key: '/"                                  |
| 0x34       | Key: //?                                  |
| 0x35       |                                           |
| 0x36       |                                           |
| 0x37       | Key: Right Arrow                          |
| 0x38       | Key: F3                                   |
| 0x39       | Key: 3                                    |
| 0x3A       | Key: E                                    |
| 0x3B       | Key: D                                    |
| 0x3C       | Key: X                                    |
| 0x3D       |                                           |
| 0x3E       | Key: Pause/Break                          |
| 0x3F       | Key: Delete                               |
| 0x40       |                                           |
| 0x41       | Key: Number Pad 7                         |
| 0x42       |                                           |
| 0x43       |                                           |
| 0x44       | Key: Num Lock                             |
| 0x45       | Key: Number Pad 6                         |
| 0x46       |                                           |
| 0x47       |                                           |
| 0x48       | Key: F4                                   |
| 0x49       | Key: 4                                    |
| 0x4A       | Key: R                                    |
| 0x4B       | Key: F                                    |
| 0x4C       | Key: C                                    |
| 0x4D       | Key: Space                                |
| 0x4E       | Key: Insert                               |
| 0x4F       | Key: End                                  |
| 0x50       |                                           |
| 0x51       | Key: Number Pad 8                         |
| 0x52       |                                           |
| 0x53       |                                           |
| 0x54       | Key: Number Pad /                         |
| 0x55       | Key: Number Pad 1                         |
| 0x56       |                                           |
| 0x57       |                                           |
| 0x58       | Key: F5                                   |
| 0x59       | Key: 5                                    |
| 0x5A       | Key: T                                    |
| 0x5B       | Key: G                                    |
| 0x5C       | Key: V                                    |
| 0x5D       |                                           |
| 0x5E       | Key: Home                                 |
| 0x5F       | Key: Page Down                            |
| 0x60       |                                           |
| 0x61       | Key: Number Pad 9                         |
| 0x62       |                                           |
| 0x63       |                                           |
| 0x64       | Key: Number Pad *                         |
| 0x65       | Key: Number Pad 2                         |
| 0x66       |                                           |
| 0x67       |                                           |
| 0x68       | Key: F6                                   |
| 0x69       | Key: 6                                    |
| 0x6A       | Key: Y                                    |
| 0x6B       | Key: H                                    |
| 0x6C       | Key: B                                    |
| 0x6D       |                                           |
| 0x6E       | Key: Page Up                              |
| 0x6F       | Key: Right Shift                          |
| 0x70       |                                           |
| 0x71       |                                           |
| 0x72       |                                           |
| 0x73       |                                           |
| 0x74       | Key: Number Pad -                         |
| 0x75       | Key: Number Pad 3                         |
| 0x76       |                                           |
| 0x77       |                                           |
| 0x78       | Key: F7                                   |
| 0x79       | Key: 7                                    |
| 0x7A       | Key: U                                    |
| 0x7B       | Key: J                                    |
| 0x7C       | Key: N                                    |
| 0x7D       | Key: Right Alt                            |
| 0x7E       | Key: ]/}                                  |
| 0x7F       | Key: Right Control                        |
| 0x80       |                                           |
| 0x81       | Key: Number Pad 4                         |
| 0x82       |                                           |
| 0x83       |                                           |
| 0x84       | Key: Number Pad +                         |
| 0x85       | Key: Number Pad 0                         |
| 0x86       |                                           |
| 0x87       |                                           |
| 0x88       | Key: F8                                   |
| 0x89       | Key: 8                                    |
| 0x8A       | Key: I                                    |
| 0x8B       | Key: K                                    |
| 0x8C       | Key: M                                    |
| 0x8D       | Key: Right Windows                        |
| 0x8E       | Key: \\/\|                                |
| 0x8F       | Key: Up Arrow                             |
| 0x90       |                                           |
| 0x91       | Key: Number Pad 5                         |
| 0x92       |                                           |
| 0x93       |                                           |
| 0x94       | Key: Number Pad Enter                     |
| 0x95       | Key: Number Pad .                         |

## **Color packet (RGB strip and media keys)**

The RGB strip and media keys are covered by a fourth color packet with color channel 4.  Different bytes in this packet provide the red, green, and blue channels for the RGB strip and media key LEDs.

| Byte Index | Description                               |
| ---------- | ----------------------------------------- |
| 0x00       | 0x07                                      |
| 0x01       | 0x06                                      |
| 0x02       | Profile to edit                           |
| 0x03       | Color channel (4: RGB Strip, Media Keys)  |
| 0x04       | 0x00                                      |
| 0x05       | 0x00                                      |
| 0x06       | 0x00                                      |
| 0x07       | 0x00                                      |
| 0x08       | RGB Strip 0 (Red)                         |
| 0x09       | RGB Strip 3 (Red)                         |
| 0x0A       | RGB Strip 5 (Red)                         |
| 0x0B       | RGB Strip 7 (Red)                         |
| 0x0C       | RGB Strip 9 (Red)                         |
| 0x0D       | RGB Strip 11 (Red)                        |
| 0x0E       | RGB Strip 13 (Red)                        |
| 0x0F       | RGB Strip 16 (Red)                        |
| 0x10       |                                           |
| 0x11       |                                           |
| 0x12       | Key: Media Mute (Red)                     |
| 0x13       | Key: Media Play Pause (Red)               |
| 0x14       |                                           |
| 0x15       |                                           |
| 0x16       |                                           |
| 0x17       |                                           |
| 0x18       |                                           |
| 0x19       | RGB Strip 3 (Green)                       |
| 0x1A       | RGB Strip 5 (Green)                       |
| 0x1B       | RGB Strip 7 (Green)                       |
| 0x1C       | RGB Strip 9 (Green)                       |
| 0x1D       | RGB Strip 11 (Green)                      |
| 0x1E       | RGB Strip 13 (Green)                      |
| 0x1F       | RGB Strip 16 (Green)                      |
| 0x20       |                                           |
| 0x21       |                                           |
| 0x22       | Key: Media Mute (Green)                   |
| 0x23       | Key: Media Play Pause (Green)             |
| 0x24       |                                           |
| 0x25       |                                           |
| 0x26       |                                           |
| 0x27       |                                           |
| 0x28       | RGB Strip 1 (Green)                       |
| 0x29       | RGB Strip 0 (Green)                       |
| 0x2A       | RGB Strip 5 (Blue)                        |
| 0x2B       | RGB Strip 7 (Blue)                        |
| 0x2C       | RGB Strip 9 (Blue)                        |
| 0x2D       | RGB Strip 11 (Blue)                       |
| 0x2E       | RGB Strip 13 (Blue)                       |
| 0x2F       | RGB Strip 16 (Blue)                       |
| 0x30       |                                           |
| 0x31       |                                           |
| 0x32       | Key: Media Mute (Blue)                    |
| 0x33       | Key: Media Play Pause (Blue)              |
| 0x34       |                                           |
| 0x35       |                                           |
| 0x36       |                                           |
| 0x37       |                                           |
| 0x38       | RGB Strip 1 (Blue)                        |
| 0x39       | RGB Strip 0 (Blue)                        |
| 0x3A       | RGB Strip 3 (Blue)                        |
| 0x3B       |                                           |
| 0x3C       |                                           |
| 0x3D       |                                           |
| 0x3E       |                                           |
| 0x3F       |                                           |
| 0x40       |                                           |
| 0x41       |                                           |
| 0x42       |                                           |
| 0x43       |                                           |
| 0x44       |                                           |
| 0x45       |                                           |
| 0x46       |                                           |
| 0x47       |                                           |
| 0x48       | RGB Strip 1 (Red)                         |
| 0x49       |                                           |
| 0x4A       |                                           |
| 0x4B       |                                           |
| 0x4C       |                                           |
| 0x4D       |                                           |
| 0x4E       |                                           |
| 0x4F       | RGB Strip 17 (Red)                        |
| 0x50       |                                           |
| 0x51       |                                           |
| 0x52       |                                           |
| 0x53       |                                           |
| 0x54       |                                           |
| 0x55       |                                           |
| 0x56       |                                           |
| 0x57       |                                           |
| 0x58       |                                           |
| 0x59       |                                           |
| 0x5A       |                                           |
| 0x5B       |                                           |
| 0x5C       |                                           |
| 0x5D       | RGB Strip 15 (Blue)                       |
| 0x5E       | RGB Strip 14 (Blue)                       |
| 0x5F       | RGB Strip 17 (Blue)                       |
| 0x60       |                                           |
| 0x61       |                                           |
| 0x62       |                                           |
| 0x63       |                                           |
| 0x64       |                                           |
| 0x65       |                                           |
| 0x66       |                                           |
| 0x67       |                                           |
| 0x68       | RGB Strip 2 (Blue)                        |
| 0x69       | RGB Strip 4 (Blue)                        |
| 0x6A       | RGB Strip 6 (Blue)                        |
| 0x6B       | RGB Strip 8 (Blue)                        |
| 0x6C       | RGB Strip 10 (Blue)                       |
| 0x6D       | RGB Strip 12 (Blue)                       |
| 0x6E       | RGB Strip 14 (Green)                      |
| 0x6F       | RGB Strip 17 (Green)                      |
| 0x70       |                                           |
| 0x71       |                                           |
| 0x72       | Key: Media Back (Blue)                    |
| 0x73       | Key: Media Forward (Blue)                 |
| 0x74       |                                           |
| 0x75       |                                           |
| 0x76       |                                           |
| 0x77       |                                           |
| 0x78       | RGB Strip 2 (Green)                       |
| 0x79       | RGB Strip 4 (Green)                       |
| 0x7A       | RGB Strip 6 (Green)                       |
| 0x7B       | RGB Strip 8 (Green)                       |
| 0x7C       | RGB Strip 10 (Green)                      |
| 0x7D       | RGB Strip 12 (Green)                      |
| 0x7E       | RGB Strip 15 (Green)                      |
| 0x7F       |                                           |
| 0x80       |                                           |
| 0x81       |                                           |
| 0x82       | Key: Media Back (Green)                   |
| 0x83       | Key: Media Forward (Green)                |
| 0x84       |                                           |
| 0x85       |                                           |
| 0x86       |                                           |
| 0x87       |                                           |
| 0x88       | RGB Strip 2 (Red)                         |
| 0x89       | RGB Strip 4 (Red)                         |
| 0x8A       | RGB Strip 6 (Red)                         |
| 0x8B       | RGB Strip 8 (Red)                         |
| 0x8C       | RGB Strip 10 (Red)                        |
| 0x8D       | RGB Strip 12 (Red)                        |
| 0x8E       | RGB Strip 15 (Red)                        |
| 0x8F       | RGB Strip 14 (Red)                        |
| 0x90       |                                           |
| 0x91       |                                           |
| 0x92       | Key: Media Back (Red)                     |
| 0x93       | Key: Media Forward (Red)                  |

## **Direct Lighting**

The color channel and color positionw work identically to the static color packets above.

| Byte Index | Value         |
| ---------- | ------------- |
| 0x00       | 0x07          |
| 0x01       | 0x16          |
| 0x02       | Color Channel |
