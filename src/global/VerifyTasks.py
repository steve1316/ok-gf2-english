"""One task per flow, so each can be run and watched on its own.

Global Daily and Global Weekly run several flows back to back, which is what you want day to day but not while checking whether a single flow works. Each
task here runs exactly one, with no toggles to set - clicking it does that flow and nothing else. They reuse the flow methods directly, so there is no second
copy of any navigation to drift out of sync.
"""

from src.region import CHECKS_GROUP, CHECKS_ICON

from .BaseGlobalTask import COMMISSIONS, START_RECHECK, START_TIME_OUT
from .GlobalDailyTask import FLOWS as DAILY_FLOWS
from .GlobalDailyTask import GlobalDailyTask
from .GlobalWeeklyTask import FLOWS as WEEKLY_FLOWS
from .GlobalWeeklyTask import GlobalWeeklyTask


def _strip_flow_toggles(task, flows):
    """Drop the composed task's per-flow toggles.

    A single-flow task always runs its one flow, so inherited toggles would be settings that do nothing. `load_config` runs later, in `after_init`, so
    removing them here keeps them out of the saved config as well as the settings panel.

    Args:
        task: The task to strip.
        flows: The parent's `FLOWS` table.
    """
    for key, method, _ in flows:
        task.default_config.pop(key, None)
        task.config_description.pop(key, None)
        # The group goes too, or its members would be nested under a toggle that no longer exists. Their
        # settings only belong on the task that runs that flow - on any other they would be dead knobs,
        # which is how every single-flow task ended up offering the Crew Deck walk timings.
        for nested in task.default_config_group.pop(key, []):
            if method != task.flow:
                task.default_config.pop(nested, None)
                task.config_description.pop(nested, None)


class _SingleFlow:
    """Shared behaviour for a task that runs exactly one flow.

    Mixed in ahead of the composed task it borrows the flow from, so `super()` in `__init__` still reaches that task. Subclasses set `flow` and `summary`, and
    `FLOWS` names the table the composed task registered, so its toggles can be taken back off again. The task is named after its flow's toggle in that table,
    so it reads the same on the Flow Checks page as it does in the Daily and Weekly settings.
    """

    FLOWS = ()
    flow = None
    summary = None

    def __init__(self, *args, **kwargs):
        """Build the task, then strip the settings that belong to the flows it will not run.

        Args:
            *args: Passed to the composed task.
            **kwargs: Passed to the composed task.
        """
        super().__init__(*args, **kwargs)
        _strip_flow_toggles(self, self.FLOWS)
        self.name = next((key for key, method, _ in self.FLOWS if method == self.flow), None)
        self.description = self.summary
        self.group_name = CHECKS_GROUP
        self.group_icon = CHECKS_ICON
        # Global Daily's first-run checklist is about the whole run, not one flow.
        self.instructions = None
        self.support_schedule_task = False

    def run(self):
        """Run the one flow this task exists for, starting from the home screen.

        Deliberately not `run_flows`, which steps over a flow that raises so the flows behind it still get a turn. There is nothing behind this one, and these
        tasks exist to show a failure rather than absorb it - the raise has to reach the executor, which is what puts the error and its screenshot on screen.
        """
        self.ensure_main(recheck_time=START_RECHECK, time_out=START_TIME_OUT)
        getattr(self, self.flow)()
        # A flow that stopped early may have parked on a screen for a flow behind it, and here there is none.
        self.leave_parked_screen()
        self.log_info(f'{self.name} finished.', notify=True)


class _SingleDailyFlow(_SingleFlow, GlobalDailyTask):
    """Runs one Global Daily flow."""

    FLOWS = DAILY_FLOWS


class _SingleWeeklyFlow(_SingleFlow, GlobalWeeklyTask):
    """Runs one Global Weekly flow."""

    FLOWS = WEEKLY_FLOWS


class RunGoHome(_SingleDailyFlow):
    """Cheapest possible check: recognise the home screen, leave it, and come back.

    It has to navigate away first. Pressing the home button while already home clicks empty space and proves nothing, so this opens Commissions - a read-only
    list - and returns from there. Buys nothing, fights nothing, spends nothing.
    """

    flow = 'go_home'
    summary = 'Opens Commissions and returns home, to check screen detection and the way back. Changes nothing.'

    def __init__(self, *args, **kwargs):
        """Build the task, then keep it out of the sidebar.

        Still registered rather than removed, because removing it would shift the `-t N` position of every task after it. The MCP remote control also
        starts it by class name as its safe idle task, which works whether or not it is visible.

        Args:
            *args: Passed to the composed task.
            **kwargs: Passed to the composed task.
        """
        super().__init__(*args, **kwargs)
        # Global Daily has no toggle for this flow to be named after.
        self.name = 'Go Home'
        self.visible = False

    def run(self):
        """Recognise the home screen, leave it for a read-only list, and come back."""
        self.log_info('checking whether the home screen is recognised')
        self.ensure_main(recheck_time=START_RECHECK, time_out=START_TIME_OUT)
        self.log_info('home screen recognised, opening Commissions so there is somewhere to come back from')
        self.click_ocr_word(COMMISSIONS, box=self.nav_strip, after_sleep=3, raise_if_not_found=True)
        if self.is_main(esc=False):
            self.log_info('still on the home screen - the Commissions click did not land', notify=True)
            return
        self.log_info('left the home screen, now testing the way back')
        self.go_home()
        self.log_info('Go Home finished.', notify=True)


class RunStartLoop(_SingleDailyFlow):
    """Opens the Dispatch Room and starts the in-game Loop."""

    flow = 'start_loop'
    summary = 'Starts the in-game Loop in the Dispatch Room and waits for it to finish.'


class RunShop(_SingleDailyFlow):
    """Claims the shop supply boxes that are currently free."""

    flow = 'shopping'
    summary = 'Claims the shop supply boxes that are currently free.'


class RunWishlist(_SingleDailyFlow):
    """Buys everything waiting in the shop Wishlist. Spends in-game currency, so it acts on its own account rather than only reporting."""

    flow = 'buy_wishlist'
    summary = 'Buys everything on the shop Wishlist.'


class RunEventSupply(_SingleDailyFlow):
    """Auto-battles the last Supply stage of the current event. Spends Expenditure."""

    flow = 'run_event_supply'
    summary = 'Auto-battles the last Supply stage of each running event.'


class RunBoundaryPush(_SingleDailyFlow):
    """Collects the Breakthrough rewards under Regular Commissions."""

    flow = 'claim_boundary_push'
    summary = 'Collects the Breakthrough rewards under Commissions.'


class RunCrewDeck(_SingleDailyFlow):
    """Runs the Crew Deck stations - makes the drink, cooks the dish, and waters the flower if that station is switched on.

    Each of those is once a day, so this spends them. A walk that stops short of its station says so in the log, which is how the timings get tuned.
    """

    flow = 'crew_deck'
    summary = 'Makes the drink, cooks the dish, and waters the flower if that is switched on.'


class RunBossFight(_SingleWeeklyFlow):
    """Spends the remaining Boss Fight attempts through the game's own Auto Mode. Costs Expenditure."""

    flow = 'boss_fight'
    summary = 'Uses the remaining Boss Fight attempts through Auto Mode.'


class RunPeakValue(_SingleWeeklyFlow):
    """Collects the Peak Value Assessment rewards."""

    flow = 'claim_peak_value'
    summary = 'Collects the Peak Value Assessment rewards.'
