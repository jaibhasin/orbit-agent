(function (root) {
  "use strict";

  function thumbnailDifference(previous, current) {
    if (!previous || !current || previous.length !== current.length || current.length === 0) {
      return 1;
    }
    let total = 0;
    for (let index = 0; index < current.length; index += 1) {
      total += Math.abs(current[index] - previous[index]);
    }
    return total / (current.length * 255);
  }

  function shouldSendFrame(options) {
    const current = options.current;
    const previousSample = options.previousSample;
    const lastSent = options.lastSent;
    if (!current || !previousSample) return false;

    const stable = thumbnailDifference(previousSample, current)
      <= Number(options.stabilityThreshold ?? 0.02);
    const changed = !lastSent || thumbnailDifference(lastSent, current)
      >= Number(options.changeThreshold ?? 0.08);
    const cooldownElapsed = Number(options.nowMs) - Number(options.lastSentAt || 0)
      >= Number(options.cooldownMs ?? 8000);

    return stable && changed && cooldownElapsed;
  }

  root.OrbitFrameChange = { thumbnailDifference, shouldSendFrame };
})(typeof globalThis !== "undefined" ? globalThis : this);
