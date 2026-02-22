"""Progress bar component using rich."""

from typing import Any

from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeRemainingColumn


class LoadingBar:
    """Wrapper around rich.Progress for showing task progress.

    Example usage:
        # Context manager style
        with LoadingBar("Processing items", total=100) as bar:
            for _ in range(100):
                # Do work...
                bar.advance()

        # Manual style
        bar = LoadingBar("Processing items", total=100)
        bar.start()
        for _ in range(100):
            # Do work...
            bar.advance()
        bar.finish()
    """

    def __init__(self, description: str, total: int):
        """Initialize a loading bar.

        Args:
            description: Text description of the task
            total: Total number of steps
        """
        self.description = description
        self.total = total
        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeRemainingColumn(),
        )
        self.task_id: TaskID | None = None

    def start(self) -> None:
        """Start the progress bar."""
        self.progress.start()
        self.task_id = self.progress.add_task(self.description, total=self.total)

    def advance(self, amount: int = 1) -> None:
        """Advance the progress bar.

        Args:
            amount: Number of steps to advance (default 1)
        """
        if self.task_id is not None:
            self.progress.update(self.task_id, advance=amount)

    def update(self, completed: int | None = None, **kwargs: Any) -> None:
        """Update progress bar properties.

        Args:
            completed: Set absolute completed count
            **kwargs: Additional properties to update
        """
        if self.task_id is not None:
            self.progress.update(self.task_id, completed=completed, **kwargs)

    def finish(self) -> None:
        """Stop and remove the progress bar."""
        self.progress.stop()

    def __enter__(self) -> "LoadingBar":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.finish()
