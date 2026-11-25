# Media provenance

The repository includes a nine-second synthetic test clip. It contains an FFmpeg test pattern and three generated tones separated by pauses. The pause-cutting demo uses this clip. Rebuild it with `sh official-media/make-demo.sh`. The full editorial workflow takes a recording with speech and three reference clips you supply.

## Optional publisher marks

Before preparing the logo catalog or running the official-mark integration tests, run `python3 official-media/fetch.py`. The script downloads three PNGs into `official-media/ai-brands/` and verifies each against the SHA256 recorded in `catalog.json`. A changed publisher file stops the download. Review and update its provenance before accepting new bytes.

| Entity | Mark used | Publisher |
| --- | --- | --- |
| Claude | Product icon | [Claude](https://claude.com/) |
| Claude Opus | Claude family icon with the model name | [Anthropic model announcement](https://www.anthropic.com/news/claude-opus-4-1) |
| Anthropic | Corporate icon | [Anthropic](https://www.anthropic.com/) |
| Gemini | Gemini product icon | [Gemini](https://gemini.google.com/) |

The catalog records the direct publisher image URLs. The publisher marks retain their respective owners and are fetched for local use. For website or news inserts, supply a screenshot you have permission to use and record its source URL and credit in the editor. Supply licensed reference videos locally as described in the project README.

## Optional amoCRM graphics

Run `python3 official-media/prepare-amocrm.py` before rebuilding the logo catalog with `prepare_libraries.py`. This optional command requires curl, FFmpeg, Poppler's `pdfimages`, Node, the globally installed HyperFrames package and Chrome. Set `REEL_CHROME` if your browser is installed elsewhere.

The script opens the [official amoCRM homepage](https://www.amocrm.ru/) in a fresh browser profile and saves the current page. It crops the official wordmark from the publisher's [image sprite](https://www.amocrm.ru/static/images/sprite.png?070720161242) and extracts two interface figures from [PDF page 34](https://www.amocrm.ru/static/assets/education/amocrm_2_instruction.pdf#page=34) and [PDF page 36](https://www.amocrm.ru/static/assets/education/amocrm_2_instruction.pdf#page=36) of the amoCRM training guide. The inbox crop excludes the sample contact sidebar. The two static publisher downloads are hash-pinned. The live homepage can change, so its capture date and actual PNG hash are recorded on each fresh setup.

The verified local bundle is published atomically to `official-media/amocrm/`. Running the command again checks the prepared files. `source.json` contains the publisher URLs, credits, speech cues and PNG hashes used by the editor. All generated files are gitignored. Publishers retain their rights; review your intended use before distributing a finished video.
