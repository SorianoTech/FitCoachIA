from pathlib import Path

from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def test_alembic_adds_src_layout_to_subprocess_import_path() -> None:
    config = Config(ROOT / "alembic.ini")

    assert Path(config.get_main_option("prepend_sys_path")).resolve() == ROOT / "src"
