# Deep Dive speaker overrides

`deepdive_speaker_overrides.json` is keyed by the string form of an insight ID.
Each entry requires:

- `host`: the official host's full name
- `guests`: a list of official guest full names
- `source_urls`: one or more official show-note, episode, feed, or transcript URLs

An entry may also include `quote_speakers`. Each item must contain `speaker` and
exactly one quote selector:

- `quote`: the full extraction quote text
- `quote_prefix`: an exact prefix of the extraction quote

Names and quote attribution must come only from official show notes, the
official episode page, or the official transcript. Never add a name or
attribution based on a guess, third-party recap, search snippet, or model
inference. Generate candidates with
`python3 pipeline/tools/match_official_transcript.py <insight_id> <official_url>`
and review every match before pasting it into the override file.
