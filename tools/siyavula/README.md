# Download English Siyavula books

Use Python 3.11 or later. The downloader uses only the standard library.

List the selected books:

```bash
python3 tools/siyavula/siyavula.py list
```

Download the English, unbranded EPUBs listed in `books.json`:

```bash
python3 tools/siyavula/siyavula.py download
```

The default directory is `$XDG_DATA_HOME/open-tutor/materials/siyavula`, or
`~/.local/share/open-tutor/materials/siyavula` when `XDG_DATA_HOME` is unset.
Existing files are checked and reused. Up to three books download concurrently.
Use `--jobs 1` for sequential downloads, or `--data-dir DIRECTORY` to choose storage.

To download one book, select its ID:

```bash
python3 tools/siyavula/siyavula.py download --book natural-sciences-and-technology-4
```

Verify the files without network access:

```bash
python3 tools/siyavula/siyavula.py verify
```

The command writes JSON to stdout and progress to stderr. An error produces a
nonzero exit code. A subset run writes `selected-books.json`; a full run writes
`inventory.json` in the data directory. Each downloaded book also has a JSON
receipt with its source URL, hash, HTTP metadata, and EPUB contents.

## Selected material

The [Siyavula catalogue](https://www.siyavula.com/read) lists these English
unbranded CC BY EPUBs, available as book files on 2026-11-12:

| Subject | South African grades |
| --- | --- |
| Natural Sciences and Technology | 4, 5, 6 |
| Natural Sciences | 7, 8, 9 |
| Mathematics | 10, 11, 12 |
| Physical Sciences | 10, 11, 12 |

These are source grade labels. They are not mappings to Swedish school years.
Some filenames for Natural Sciences 7–9 say `PhysicalSciences`; the catalogue
classifies those books as Natural Sciences.

Two further catalogue entries, Mathematical Literacy 10 and Life Sciences 10,
return Git LFS pointer text instead of EPUBs. A pointer identifies a file stored
elsewhere; it does not contain the book. Their URLs, expected object hashes, and
sizes are recorded under `unavailable` in `books.json`. The downloader excludes
them from the default selection and reports them in the inventory.

The selection excludes branded CC BY-ND files, teacher guides, Afrikaans books,
and closed-copyright IT and CAT books. The catalogue offers mathematics 7–9 as
branded PDFs rather than unbranded CC BY EPUBs.

## Source and license records

`books.json` identifies each source file and pins its SHA-256 after verification.
The downloader checks that every selected URL remains listed as an English
unbranded EPUB before downloading. It saves the catalogue HTML in the data directory.

The catalogue describes unbranded books under
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). Embedded notices can
differ: the downloaded Grade 4 front matter states CC BY 4.0. The inventory keeps
the catalogue license URL and the license links found inside each book separately.
Keep each book's credits and image attribution when using its contents.

Credit Siyavula Education and the contributors named in each book. The downloaded
EPUBs are unchanged originals. Source URLs and hashes make the files reproducible
without committing large books to Git.

## Validation

The inspector checks the SHA-256, ZIP integrity, EPUB mimetype, package document,
reading order, English language metadata, and readable text. Its report includes
the original internal document paths, text counts, image counts, and missing
manifest resources. It does not certify EPUB standards compliance or visual layout.

Downloads become final files only after inspection. A partial download has a
temporary `.part` filename. If an existing book fails verification, move that file
out of the data directory and rerun `download` to fetch a fresh copy.

Run the focused tests:

```bash
python3 -m unittest discover -s tools/siyavula/tests
```
