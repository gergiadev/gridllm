def run_tui(grid, task: str, bus) -> None:
    from .app import GridApp

    app = GridApp(grid=grid, task=task, bus=bus)
    app.run()


__all__ = ["run_tui"]