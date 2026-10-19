"""Android automation agent — ADB + vision LLM, designed to run inside Termux.

No cloud UI service, no PC required. The agent observes the screen
(screenshot + uiautomator dump), asks a vision model what to do next,
and executes the action through ADB.
"""

__version__ = "0.1.0"
