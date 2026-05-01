# VHS tape script for deterministic recording of the SOX Protocol two-agent demo.
#
# Prerequisites: vhs (https://github.com/charmbracelet/vhs) installed and on PATH.
# To regenerate the recording:
#
#   cd /path/to/sox-protocol
#   vhs examples/two-agents-talking/demo.tape
#
# Outputs:
#   docs/media/demo.gif   — rendered GIF for README embed
#   docs/media/demo.cast  — asciinema-compatible .cast for launch posts

Output docs/media/demo.cast
Output docs/media/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 120
Set Height 40
Set Theme "Dracula"
Set Padding 10

# Title frame
Type "# SOX Protocol — Two Agents Talking Demo"
Sleep 1s
Enter

# Run the demo script
Type "python3 examples/two-agents-talking/demo.py"
Sleep 500ms
Enter

# The script runs for 45 seconds — sleep while it runs
Sleep 47s

# Hold on final output
Sleep 3s
