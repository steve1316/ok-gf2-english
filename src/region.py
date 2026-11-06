import importlib

from ok import ConfigOption, Logger
from ok.util.file import get_relative_path, read_json_file
from src import start_lock

logger = Logger.get_logger(__name__)

# Window title, About tab name, and exported log zip name. Set here rather than in upstream's `src/config.py` so the rename never conflicts on a merge.
APP_TITLE = "ok-gf2-english"

# What the run bar calls the game, as in "Start Girls' Frontline 2". Without it the bar says "Start Game".
GAME_NAME = "Girls' Frontline 2"

# The smallest window the Tasks page fits in: 216 sidebar + 372 task list + ~340 detail pane + margins, and 600 tall so the detail pane keeps some settings on
# screen. At upstream's 600x450 the detail pane slides over the task list.
MIN_WINDOW_SIZE = {"min_width": 1000, "min_height": 600}

# The About tab's GitHub and FAQ buttons. Upstream's point at their CN repo, where questions about this fork do not belong. Discord, sponsor and QQ links
# are the upstream author's own community, so they are left alone.
APP_LINKS = {"github": "https://github.com/steve1316/ok-gf2-english", "faq": "https://github.com/steve1316/ok-gf2-english#-troubleshooting"}

# Set on a task class once its post_init has been wrapped, so re-importing this module cannot nest wrappers.
HIDDEN_MARKER = "_ok_gf2_region_hidden"

# Same guard for the framework's Diagnosis task, once it has been moved onto the Flow Checks page.
CHECKS_MARKER = "_ok_gf2_flow_checks"

# The Tasks page filter tab the single-flow tasks live on. They are run while fixing something, not every day, so they should not bury Global Daily and Global
# Weekly. Grouping only changes where they are drawn - their `-t N` positions come from the registration order and do not move.
CHECKS_GROUP = "Flow Checks"
CHECKS_ICON = "bug"

# The framework's own performance test. It is run while fixing something, like the single-flow tasks, and "Performance Test" did not say what it tests.
DIAGNOSIS_TEXT = "Measures screen capture and OCR speed on this PC."

REGION_CONFIG_NAME = "Region"
REGION_CONFIG_KEY = "Game Client"
REGION_GLOBAL = "Global"
REGION_CN = "CN"
REGION_DEFAULT = REGION_GLOBAL

# Module prefix of the CN task package. Anything registered from there belongs to the CN client.
CN_TASK_PREFIX = "src.tasks."

# Module prefix of upstream's own settings tabs. Both are built on `ok.gui` and qfluentwidgets, which ok-script 3 removed, so loading either crashes the app at
# startup. They stay dropped in both regions until upstream moves to ok-script 3, and the files are left alone so upstream merges stay clean.
CN_TAB_PREFIX = "src.gui."

# Tasks that drive the Global client. They live in src/global/ and match English on-screen text
# directly instead of going through the reverse ocr.po translation.
GLOBAL_TASKS = [
    ["src.global.GlobalDailyTask", "GlobalDailyTask"],
    ["src.global.GlobalWeeklyTask", "GlobalWeeklyTask"],
    # One button per flow, for checking a single flow without running the rest. Appended after the
    # composed tasks so their positions never move.
    ["src.global.VerifyTasks", "RunGoHome"],
    ["src.global.VerifyTasks", "RunStartLoop"],
    ["src.global.VerifyTasks", "RunShop"],
    ["src.global.VerifyTasks", "RunEventSupply"],
    ["src.global.VerifyTasks", "RunBoundaryPush"],
    ["src.global.VerifyTasks", "RunPeakValue"],
    ["src.global.VerifyTasks", "RunCrewDeck"],
    ["src.global.VerifyTasks", "RunWishlist"],
    ["src.global.VerifyTasks", "RunBossFight"],
]

region_option = ConfigOption(
    REGION_CONFIG_NAME,
    {REGION_CONFIG_KEY: REGION_DEFAULT},
    config_type={REGION_CONFIG_KEY: {"type": "drop_down", "options": [REGION_GLOBAL, REGION_CN]}},
    config_description={REGION_CONFIG_KEY: "Which game client to automate. Restart the app to apply."},
    icon="globe",
)


def current_region(config_folder="configs"):
    """Read the selected region straight off disk.

    The task list has to be built while `src/config.py` is still being imported, which is before the framework instantiates its own `Config` objects. Both
    paths resolve the same `Region.json`, so reading it directly here stays in sync with whatever the settings tab writes.

    Args:
        config_folder: Folder holding the config JSON files. Comes from the app config so it cannot drift from where the settings tab writes.

    Returns:
        Either `REGION_GLOBAL` or `REGION_CN`. Falls back to `REGION_DEFAULT` when the file is missing or holds an unknown value.
    """
    saved = read_json_file(get_relative_path(config_folder, f"{REGION_CONFIG_NAME}.json")) or {}
    region = saved.get(REGION_CONFIG_KEY, REGION_DEFAULT)
    return region if region in (REGION_GLOBAL, REGION_CN) else REGION_DEFAULT


def already_hidden(task_class, marker=HIDDEN_MARKER):
    """Whether this class has had its own `post_init` wrapped already.

    Looked up on the class itself rather than through its bases. Every task in `VerifyTasks` subclasses a composed task, so an inherited marker would report
    them as already wrapped and leave them visible in the region they do not belong to.

    Args:
        task_class: The task class to check.
        marker: The class attribute the wrap left behind. `HIDDEN_MARKER` unless the wrap made some other change.

    Returns:
        True when this class, not merely an ancestor, carries the marker.
    """
    return marker in task_class.__dict__


def _set_after_post_init(module_path, class_name, marker, **attributes):
    """Wrap a registered task's `post_init` so every instance ends up with `attributes` set.

    The framework builds every registered task and only then reads attributes like `visible` and `group_name` off each instance. `BaseTask.__init__` sets
    them all, so a class attribute would not survive, and `post_init` is the one hook that runs after it. Patching it from here keeps upstream's and the
    framework's own files untouched, which matters because they get merged in regularly.

    Args:
        module_path: Module the task class is registered from.
        class_name: The task class's name in that module.
        marker: Class attribute set once wrapped, so re-importing this module cannot nest wrappers.
        **attributes: Instance attributes to set after the original `post_init` runs.
    """
    try:
        task_class = getattr(importlib.import_module(module_path), class_name)
    except (ImportError, AttributeError):
        logger.warning(f'could not change {module_path}.{class_name}, it was registered but does not exist')
        return
    if already_hidden(task_class, marker):
        return
    original = task_class.post_init

    def post_init(self):
        original(self)
        for name, value in attributes.items():
            setattr(self, name, value)

    task_class.post_init = post_init
    setattr(task_class, marker, True)


def _move_diagnosis_to_checks():
    """Put the framework's Diagnosis task on the Flow Checks page, described by what it measures."""
    _set_after_post_init("ok", "DiagnosisTask", CHECKS_MARKER, group_name=CHECKS_GROUP, group_icon=CHECKS_ICON, description=DIAGNOSIS_TEXT)


def _hide_tasks(task_entries):
    """Keep the given task classes off the Tasks page.

    Args:
        task_entries: `[module_path, class_name]` pairs to hide.
    """
    for module_path, class_name in task_entries:
        _set_after_post_init(module_path, class_name, HIDDEN_MARKER, visible=False)


def apply_region(config):
    """Register the Region setting and hide whichever region's tasks are not selected, along with upstream's CN-only trigger tasks on Global.

    Global tasks are appended to whatever `src/config.py` already registered rather than replacing it. That keeps upstream as the single source of truth for
    its own task list, and it keeps every existing position stable - desktop shortcuts and Windows scheduled tasks store a positional index into this list
    ("-t N"), so reordering it would silently repoint them at the wrong task.

    The app is also named `APP_TITLE`, the game `GAME_NAME`, its About links point at `APP_LINKS`, upstream's tabs are dropped, and the other Start buttons are
    locked while a task runs, whichever region is selected.

    Args:
        config: The app config dict from `src/config.py`, mutated in place.
    """
    config["gui_title"] = APP_TITLE
    config["game_name"] = GAME_NAME
    config["window_size"] = {**config.get("window_size", {}), **MIN_WINDOW_SIZE}
    # Only the buttons a language already shows are repointed. zh_CN has no FAQ entry of its own.
    for links in config.get("links", {}).values():
        links.update({key: url for key, url in APP_LINKS.items() if key in links})
    start_lock.apply()
    # Dropped outright rather than hidden. This list is not indexed by "-t N".
    config["custom_tabs"] = [entry for entry in config.get("custom_tabs", []) if not entry[0].startswith(CN_TAB_PREFIX)]
    config.setdefault("global_configs", []).append(region_option)
    registered = config["onetime_tasks"]
    cn_tasks = [entry for entry in registered if entry[0].startswith(CN_TASK_PREFIX)]
    config["onetime_tasks"] = registered + GLOBAL_TASKS
    if current_region(config.get("config_folder", "configs")) != REGION_GLOBAL:
        _hide_tasks(GLOBAL_TASKS)
        return
    _hide_tasks(cn_tasks)
    _move_diagnosis_to_checks()
    # A registered trigger task can still run in the background, so hiding would not be enough.
    config["trigger_tasks"] = [entry for entry in config.get("trigger_tasks", []) if not entry[0].startswith(CN_TASK_PREFIX)]
