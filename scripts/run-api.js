const { spawn } = require("child_process");
const path = require("path");

const root = path.join(__dirname, "..");
const python =
  process.platform === "win32"
    ? path.join(root, "venv", "Scripts", "python.exe")
    : path.join(root, "venv", "bin", "python");

const child = spawn(
  python,
  ["-m", "uvicorn", "backend.app.main:app", "--port", "8000", "--reload"],
  { stdio: "inherit", cwd: root, shell: process.platform === "win32" },
);

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
