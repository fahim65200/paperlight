# Paperlight

Free research and document tools that run in the browser, plus a thesis search for Bangladeshi universities.

## Put the site online (GitHub Pages)
1. Upload everything in this folder to a public GitHub repository, keeping the folders.
2. Settings > Pages > Source: **Deploy from a branch**, branch **main**, folder **/ (root)** > Save.
3. After a few minutes the site is at `https://YOUR-USERNAME.github.io/REPOSITORY-NAME/`.

## Turn on the thesis collector
The collector (`collector/collect.py`) visits university repositories and writes `atlas/theses.json`.
It runs every Monday, and you can run it any time:

1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Collect theses** > **Run workflow** > **Run workflow**.
3. When it finishes (a few minutes to an hour), open the run to see a table of results per university.

If the run fails with a permission error when saving: Settings > Actions > General > Workflow permissions > **Read and write permissions** > Save, then run again.

If the `.github` folder didn't upload (it can be hidden on Mac): Add file > Create new file, name it `.github/workflows/collect.yml`, and paste the contents of that file from the zip.

## Add a university
Edit `collector/sources.json` and copy one of the blocks. Most Bangladeshi repositories use DSpace;
the OAI address is usually the repository address with `/oai/request` at the end.

## Hand-checked theses
`atlas/theses.js` holds theses checked one by one (with journal citations where known). They always stay in the index.
