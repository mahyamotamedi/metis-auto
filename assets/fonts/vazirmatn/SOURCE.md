# Vazirmatn (bundled font, UI spec UI-V08)

- Project: https://github.com/rastikerdar/vazirmatn (Saber Rastikerdar and the Vazirmatn Project Authors, see `AUTHORS.txt`).
- Release: **v33.003** (published 2022-06-22; the latest release on 2026-11-03).
- Archive: https://github.com/rastikerdar/vazirmatn/releases/download/v33.003/vazirmatn-v33.003.zip, sha256 `0a9afd41967e6f57096a56a181a23f81a2b999b62f1f2a4e4b26736580854fdb`, downloaded 2026-11-03.
- Licence: SIL Open Font License 1.1, `OFL.txt` (copied unchanged from the archive).
- Files taken unchanged from `fonts/webfonts/` in the archive:

| File | Weight | sha256 |
|---|---|---|
| `Vazirmatn-Regular.woff2` | 400 | `e382101336c6eb32cfb31381c027d02d2e0354bad08f6a395d4088beb3db3d91` |
| `Vazirmatn-Medium.woff2` | 500 | `3333e31188a2b628db8780ca22fd5aad85bc083ccee9beb8d4d52db18cb98d48` |
| `Vazirmatn-Bold.woff2` | 700 | `836fae7d42d83faa249bc00e0099592be98a1fa260d22d82f269b6091e585627` |
| `Vazirmatn-ExtraBold.woff2` | 800 (the wordmark only) | `cd67558bbca0ad319b89e3b2edb8a914f87f864951d7a9d24e1404cbf3b45b02` |
| `OFL.txt` | licence | `17e355067c8284f47743a1ee3b1ef7ff684ff0601eda357f9353b10b3016ab31` |
| `AUTHORS.txt` | authors | `b57746a5f7002c0974c76c32af74079ff7ef1aaf8f35495e9409cfa1eb11e1ca` |

Served offline: `metis_auto.wiring.ui_style.font_face_css` embeds them as base64 `@font-face` rules (Streamlit 1.65.0 static serving reads only `scripts/static/`), see ADR-0052. The weights in use are listed in `config/demo/theme.toml` `[font]`.
