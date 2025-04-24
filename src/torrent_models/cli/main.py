from datetime import timedelta
from pathlib import Path
from time import time
from typing import Literal as L

import click
import humanize

from torrent_models.const import DEFAULT_TORRENT_CREATOR
from torrent_models.info import InfoDictHybridCreate
from torrent_models.torrent import TorrentCreate, list_files
from torrent_models.types import V1PieceLength, V2PieceLength


@click.group("torrentpd")
def main() -> None:
    """
    torrent-models CLI
    """


@main.command("make")
@click.option(
    "-p",
    "--path",
    required=True,
    help="Path to a directory or file to create .torrent from",
    type=click.Path(exists=True),
)
@click.option(
    "-t",
    "--tracker",
    required=False,
    default=None,
    multiple=True,
    help="Trackers to add to the torrent. can be used multiple times for multiple trackers. ",
)
@click.option(
    "-s",
    "--piece-size",
    default=512 * (2**10),
    help="Piece size, in bytes",
    show_default=True,
)
@click.option(
    "--comment",
    default=None,
    required=False,
    help="Optional comment field for torrent",
)
@click.option(
    "--creator",
    default=DEFAULT_TORRENT_CREATOR,
    show_default=True,
    required=False,
    help="Optional creator field for torrent",
)
@click.option(
    "-w",
    "--webseed",
    required=False,
    default=None,
    multiple=True,
    help="Add HTTP webseeds as additional sources for torrent. Can be used multiple times. "
    "See https://www.bittorrent.org/beps/bep_0019.html",
)
@click.option(
    "--similar",
    required=False,
    default=None,
    multiple=True,
    help="Add infohash of a similar torrent. "
    "Similar torrents are torrents who have files in common with this torrent, "
    "clients are able to reuse files from the other torrents if they already have them downloaded.",
)
@click.option(
    "--version",
    default="hybrid",
    type=click.Choice(["v1", "v2", "hybrid"]),
    help="What kind of torrent to create, default is hybrid",
)
@click.option("--progress/--no-progress", default=True, help="Enable progress bar (default True)")
@click.option(
    "-o",
    "--output",
    required=False,
    default=None,
    type=click.Path(exists=False),
    help=".torrent file to write to. Otherwise to stdout",
)
def make(
    path: Path,
    tracker: list[str] | tuple[str] | None = None,
    piece_size: V1PieceLength | V2PieceLength = 512 * (2**10),
    comment: str | None = None,
    creator: str = DEFAULT_TORRENT_CREATOR,
    webseed: list[str] | None = None,
    similar: list[str] | None = None,
    version: L["v1", "v2", "hybrid"] = "hybrid",
    progress: bool = True,
    output: Path | None = None,
) -> None:
    path = Path(path)
    files = list_files(path)
    start_time = time()
    created = TorrentCreate(
        trackers=tracker,
        files=files,
        path_root=path,
        comment=comment,
        creator=creator,
        info=InfoDictHybridCreate(piece_length=piece_size, name=path.name),
    )
    generated = created.generate(version=version, progress=progress)
    bencoded = generated.bencode()
    if output:
        with open(output, "wb") as f:
            f.write(bencoded)

        torrent_size = Path(output).stat().st_size

        end_time = time()
        duration = end_time - start_time
        total_size = generated.info.total_length
        speed = total_size / duration
        click.echo(
            f"Created torrent {output}\n"
            f"Total size: {humanize.naturalsize(total_size, binary=True)}\n"
            f"Torrent size: {humanize.naturalsize(torrent_size, binary=True)}\n"
            f"Duration: {humanize.naturaldelta(timedelta(seconds=duration))}\n"
            f"Speed: {humanize.naturalsize(speed, binary=True)}/s"
        )
    else:
        click.echo(bencoded)
