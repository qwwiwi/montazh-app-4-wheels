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
