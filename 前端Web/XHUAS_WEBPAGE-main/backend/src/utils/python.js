function resolvePythonBin() {
  if (process.env.XHAUS_PYTHON) {
    return process.env.XHAUS_PYTHON;
  }
  if (process.env.PYTHON) {
    return process.env.PYTHON;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function pythonCandidates() {
  return Array.from(
    new Set(
      [
        process.env.XHAUS_PYTHON,
        process.env.PYTHON,
        process.platform === "win32" ? "python" : "python3",
        "python",
        "python3",
      ].filter(Boolean),
    ),
  );
}

module.exports = {
  resolvePythonBin,
  pythonCandidates,
};
