# Mera Galeni Folia

"Just the pages of Galen"

## About

_Mera Galenia folia_ is a static-site build of the Galenus Verbatim project.

Ce projet a bénéficié du financement de
l'[Institut universitaire de France](https://www.iufrance.fr), ainsi que de
l'[Initiative humanités biomédicales de l'Alliance Sorbonne Université](https://humanites-biomedicales.sorbonne-universite.fr) pour sa partie latine.

It uses [Kodon](https://github.com/perseusdlcode/kodon-py) to parse its TEI
XML files into a format that renders straightforwardly in the browser, without
the need for XSLTs. Kodon's format also makes further annotation trivial by
identifying each token in the corpus with a unique
[CTS URN](https://cite-architecture.github.io/ctsurn_spec/).

In addition to Galenus Verbatim, Kodon has been developed under the auspices of the
[_Ajax_ Multi-Commentary](https://multi.ajmch.ch), which was generously by the Swiss
National Science Foundation under an Ambizione grant (no.
[PZ00P1_186033](https://data.snf.ch/grants/grant/186033)).

Kodon has received further support from the Perseus Project.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

To get started with development, clone this repository and initialize a virtual
environment:

```sh
$ git clone https://github.com/galenus-verbatim/mera-galeni-folia
$ cd mera-galeni-folia
$ uv venv .venv
```

To start the development server, simply run `$ uv run galenus-dev` from
the root directory of this repository.

## Building

The static files are built using [Frozen Flask](https://frozen-flask.readthedocs.io/en/latest/).
Run `uv run galenus` to build them.

There is currently a GitHub action at `./.github/workflows/deploy.yml` which builds
the static version of the site on every push to `main`.

# LICENSE

MIT License

Copyright (c) 2026 Nathalie Rousseau

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
