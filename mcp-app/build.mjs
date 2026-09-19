import { build } from "esbuild";
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

const root = new URL(".", import.meta.url);
const nativeRoot = new URL("../src/outtake/static/", root);
const result = await build({
  absWorkingDir: root.pathname,
  entryPoints: ["app.js"],
  bundle: true,
  minify: true,
  write: false,
  format: "esm",
  target: "es2022",
  charset: "utf8",
  legalComments: "inline",
  metafile: true,
});
// The portable view is an Apps SDK transport for the dashboard, not a second
// presentation.  Always start with the native document and stylesheet so a
// dashboard change cannot silently leave the MCP view on a different layout.
const nativeIndex = await readFile(new URL("index.html", nativeRoot), "utf8");
const nativeCss = await readFile(new URL("app.css", nativeRoot), "utf8");
const template = nativeIndex
  .replace(
    '<link rel="stylesheet" href="/app.css" />',
    `<style data-outtake-native-css>${nativeCss}</style>`,
  )
  .replace(
    '<script src="/app.js" defer></script>',
    "<!-- APP_SCRIPT -->",
  );
const script = result.outputFiles[0].text.replaceAll("</script", "<\\/script");
const packaged = new URL("../src/outtake/resources/mcp_app.html", root);
await writeFile(
  packaged,
  template.replace(
    "<!-- APP_SCRIPT -->",
    () => `<script type="module">${script}</script>`,
  ),
);

// Keep the notice deterministic: inputs are sorted and only package metadata and
// license text are copied. esbuild itself is a build-time dependency and is not
// part of the browser bundle.
const packages = new Set();
for (const input of Object.keys(result.metafile.inputs).sort()) {
  const pieces = path
    .resolve(root.pathname, input)
    .split(`${path.sep}node_modules${path.sep}`);
  if (pieces.length < 2) continue;
  const tail = pieces.at(-1).split(path.sep);
  packages.add(
    pieces.slice(0, -1).join(`${path.sep}node_modules${path.sep}`) +
      `${path.sep}node_modules${path.sep}` +
      tail.slice(0, tail[0].startsWith("@") ? 2 : 1).join(path.sep),
  );
}
let licenses =
  "Third-party notices for the bundled Outtake MCP Apps view\n\n";
for (const directory of [...packages].sort()) {
  const metadata = JSON.parse(
    await readFile(path.join(directory, "package.json"), "utf8"),
  );
  const license = (await readdir(directory)).find((name) =>
    /^licen[cs]e(?:\..*)?$/i.test(name),
  );
  if (!license) throw new Error(`Missing license for ${metadata.name}`);
  licenses += `${metadata.name} ${metadata.version}\n${await readFile(
    path.join(directory, license),
    "utf8",
  )}\n\n`;
}
await writeFile(
  new URL("../src/outtake/resources/mcp_app.LICENSE.txt", root),
  licenses.replace(/[ \t]+$/gm, "").trimEnd() + "\n",
);