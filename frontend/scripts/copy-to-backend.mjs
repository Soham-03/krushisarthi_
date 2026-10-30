import { cpSync, rmSync, existsSync } from "node:fs";
const dest = "../backend/static";
if (existsSync(dest)) rmSync(dest, { recursive: true, force: true });
cpSync("dist", dest, { recursive: true });
console.log("Copied build to backend/static");
