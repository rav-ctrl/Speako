-- Hammerspoon config: Cmd+Shift+R speaks the current selection via tts_client.py
-- Symlink or copy this file to ~/.hammerspoon/init.lua (setup.sh does this).

local TTS_DIR = os.getenv("HOME") .. "/tts-hotkey"
local PYTHON = TTS_DIR .. "/.venv/bin/python3"
local CLIENT = TTS_DIR .. "/tts_client.py"

hs.hotkey.bind({"cmd", "shift"}, "R", function()
    local task = hs.task.new(PYTHON, function(exitCode, stdOut, stdErr)
        if exitCode ~= 0 then
            hs.alert.show("TTS error: " .. (stdErr or "?"), 2)
        end
    end, {CLIENT})
    task:start()
end)

hs.alert.show("TTS hotkey loaded (Cmd+Shift+R)", 1)
