---
file_format: mystnb
mystnb:
    output_stderr: remove
    render_text_lexer: python
    render_markdown_format: myst
myst:
    enable_extensions: ["colon_fence"]
---

# torrent-models

Welcome, you have reached a website that is about a software program for
using bittorrent `.torrent` files.

```{tip}
If you intended to be on a different website,
please consult the world wide web on the browser for your device. 
```

---

This program is about using {class}`pydantic <pydantic.BaseModel>` data models to create, edit, and extend `.torrent` files.

While there are [many](#other-projects) other torrent packages, this one:

- Is simple and focused
- Can create and parse v1, v2, hybrid, and [other BEPs](./beps.md)
- Is focused on library usage (but does [cli things too](./usage/cli.md))
- Validates torrent files (e.g. when accepting them as user input!)
- Treats .torrent files as an *extensible* rather than fixed format
- Is performant! (and asyncio compatible when hashing!)
- Uses python typing and is mypy friendly

## Examples

### Read a torrent

```{code-cell}
from torrent_models import Torrent

torrent = Torrent.read("tentacoli-1977-ost.torrent")
torrent.pprint(verbose=1)   
```

### Edit a torrent

It's just a normal pydantic model!

```{code-cell}
---
tags: ["hide-output"]
---

from rich import print
print(torrent)
```

It handles conversion to and from bytes and strings,
so within python it works as expected and you don't need to worry about serialization.

```{code-cell}
torrent.announce_list = [[torrent.announce], ["https://example.com/announce"]]
torrent.comment = "you better believe it's great, seriously check it out"
torrent.created_by = "not me, but i like them whoever they are"

torrent.write('new-tentacoli.torrent')
edited = Torrent.read('new-tentacoli.torrent')
edited.pprint()
```

## Create a torrent

Have files but no torrent? no problem.
`torrent-models` has a special :class:`~torrent_models.TorrentCreate` class
with convenience methods and fields for creating torrents

```{code-cell}
from pathlib import Path
import random

from torrent_models import TorrentCreate, MiB

folder = Path("my_files")
folder.mkdir(exist_ok=True)
for file in ('secrets.bin', 'plots.bin'):
    with open(folder / file, 'wb') as f:
        f.write(random.randbytes(random.randint(10*(2**10), 10*(2**20))))

new = TorrentCreate(path_root=folder, piece_length=1 * MiB, announce="udp://example.com:6969")
v1 = new.generate("v1")
v2 = new.generate("v2") 
hybrid = new.generate("hybrid")    
```  

```{code-cell}
---
tags: ["hide-output"]
---

v1.pprint(verbose=3)
```

```{code-cell}
---
tags: ["hide-output"]
---

v2.pprint(verbose=3)
```

```{code-cell}
---
tags: ["hide-output"]
---

hybrid.pprint(verbose=3) 
```

## Installation

From pypi

```shell
python -m pip install torrent-models
```

From git

```shell
git clone https://github.com/p2p-ld/torrent-models
cd torrent-models
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```





## Other Projects


These are also good projects, and probably more battle tested
(but we don't know them well and can't vouch for their use):

- [`torrentfile`](https://alexpdev.github.io/torrentfile/)
- [`dottorrent`](https://dottorrent.readthedocs.io)
- [`torf`](https://github.com/rndusr/torf)
- [`torrenttool`](https://github.com/idlesign/torrentool)
- [`PyBitTorrent`](https://github.com/gaffner/PyBitTorrent)
- [`torrent_parser`](https://github.com/7sDream/torrent_parser)

The reasons we did not use these other tools and wrote this one:

- `torf` has some notable performance problems, and doesn't support v2.
  In several issues, the maintainer has signaled that the package needs to be rewritten,
  and will not support v2 until then.
- `torrentfile` is focused on the cli and doesn't appear to be able to validate torrent files, 
  and there is no dedicated method for parsing them, 
  e.g. editing [directly manipulates the bencoded dict](https://github.com/alexpdev/torrentfile/blob/d50d942dc72c93f052c63b443aaec38c592a14df/torrentfile/edit.py#L65)
  and [rebuilding requires the files to be present](https://github.com/alexpdev/torrentfile/blob/d50d942dc72c93f052c63b443aaec38c592a14df/torrentfile/rebuild.py)
- `dottorrent` can only write, not parse torrent files.
- `torrenttool` doesn't validate torrents
- `PyBitTorrent` doesn't validate torrents
- `torrent_parser` doesn't validate torrents and doesn't have a torrent file class


```{toctree}
:caption: Usage:

usage/torrent
usage/cli
```

```{toctree}
:caption: API:

api/create
api/hashing
api/info
api/libtorrent
api/torrent
api/types
```

```{toctree}
:maxdepth: 2
:caption: Reference:

beps
references
changelog
```

