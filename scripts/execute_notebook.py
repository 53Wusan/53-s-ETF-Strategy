from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = (
    Path(sys.argv[1]).resolve()
    if len(sys.argv) > 1
    else ROOT / "notebooks" / "01_t5_reconstruction.ipynb"
)


def execute_notebook() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    client = NotebookClient(
        notebook,
        timeout=900,
        kernel_name="python3",
        resources={"metadata": {"path": str(ROOT)}},
        allow_errors=False,
        shutdown_kernel="immediate",
    )
    with client.setup_kernel():
        for cell_index, cell in enumerate(notebook.cells):
            if cell.cell_type == "code":
                client.execute_cell(cell, cell_index)
                nbformat.write(notebook, NOTEBOOK_PATH)
    print(f"Executed {NOTEBOOK_PATH}")


if __name__ == "__main__":
    execute_notebook()
