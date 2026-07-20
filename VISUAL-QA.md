# Visual QA

Use the shared CSolutions Playwright runner for real browser screenshots before marking visual work complete.

## Commands

Start this repo's dev server first, then replace the URL below with the local URL and port for this project:

```bash
/home/cresp3/scripts/visual-check-init.sh .
/home/cresp3/scripts/visual-check.sh --url http://localhost:3000/ --out .visual-checks/home-mobile.png
/home/cresp3/scripts/visual-check.sh --desktop --url http://localhost:3000/ --out .visual-checks/home-desktop.png
```

For a specific section, use a CSS selector:

```bash
/home/cresp3/scripts/visual-check.sh --url http://localhost:3000/ --selector "main" --out .visual-checks/main-section.png
```

For tall pages, crop the full-page screenshot:

```bash
/home/cresp3/scripts/visual-check.sh --desktop --url http://localhost:3000/ --out .visual-checks/full.png --ffmpeg-crop 1440:900:0:1200 --crop-out .visual-checks/section.png
```

## Rule

Do not rely only on Tailwind/class-name reasoning for layout, responsive spacing, animations, or polish. Render the page, inspect the screenshot, then iterate.

Keep `.visual-checks/` local unless Carlos explicitly asks to commit evidence screenshots.
