"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const extensionDir = path.join(__dirname, "..", "extension", "orbit-audio-capture");

async function testToolbarActivationReportsStatus() {
  const runtimeListeners = [];
  const actionListeners = [];
  const commandListeners = [];
  const sentTabMessages = [];

  const context = {
    chrome: {
      action: {
        onClicked: {
          addListener(listener) {
            actionListeners.push(listener);
          }
        }
      },
      commands: {
        onCommand: {
          addListener(listener) {
            commandListeners.push(listener);
          }
        }
      },
      offscreen: {
        async createDocument() {}
      },
      runtime: {
        lastError: null,
        onMessage: {
          addListener(listener) {
            runtimeListeners.push(listener);
          }
        },
        async getContexts() {
          return [];
        },
        getURL(filePath) {
          return `chrome-extension://orbit/${filePath}`;
        },
        async sendMessage(message) {
          assert.equal(message.type, "ORBIT_OFFSCREEN_START");
          return { ok: true };
        }
      },
      storage: {
        session: {
          async set() {},
          async get() {
            return {};
          }
        }
      },
      tabCapture: {
        getMediaStreamId(_options, callback) {
          callback("stream-id");
        }
      },
      tabs: {
        async query() {
          return [{ id: 7 }];
        },
        async sendMessage(tabId, message) {
          sentTabMessages.push({ tabId, message });
        }
      }
    },
    console
  };

  vm.runInNewContext(
    fs.readFileSync(path.join(extensionDir, "service_worker.js"), "utf8"),
    context
  );

  await new Promise((resolve, reject) => {
    const handled = runtimeListeners[0](
      {
        type: "ORBIT_CAPTURE_CONFIG",
        sessionId: "session-1",
        meetingId: "abc-defg-hij",
        webSocketUrl: "ws://127.0.0.1:8000/internal/audio-stream/session-1"
      },
      { tab: { id: 7 } },
      (response) => {
        try {
          assert.equal(response.ok, true);
          assert.equal(response.cached, true);
          resolve();
        } catch (error) {
          reject(error);
        }
      }
    );
    assert.equal(handled, true);
  });

  await actionListeners[0]({ id: 7 });

  assert.equal(sentTabMessages.length, 1);
  assert.equal(sentTabMessages[0].tabId, 7);
  assert.equal(sentTabMessages[0].message.type, "ORBIT_CAPTURE_STATUS");
  assert.equal(sentTabMessages[0].message.ok, true);
  assert.equal(sentTabMessages[0].message.error, undefined);
}

function testContentScriptDisplaysActiveStatus() {
  const runtimeListeners = [];
  const button = {
    disabled: false,
    style: {},
    textContent: "Use Alt+Shift+O or the extension icon"
  };

  const context = {
    chrome: {
      runtime: {
        onMessage: {
          addListener(listener) {
            runtimeListeners.push(listener);
          }
        }
      }
    },
    console,
    document: {
      addEventListener() {},
      getElementById(id) {
        assert.equal(id, "orbit-audio-capture-button");
        return button;
      },
      querySelectorAll() {
        return [];
      }
    },
    window: {
      addEventListener() {}
    }
  };

  vm.runInNewContext(
    fs.readFileSync(path.join(extensionDir, "content.js"), "utf8"),
    context
  );

  runtimeListeners[0]({ type: "ORBIT_CAPTURE_STATUS", ok: true });

  assert.equal(button.textContent, "Orbit capture active");
  assert.equal(button.disabled, true);
  assert.equal(button.style.opacity, "0.72");
}

function testContentScriptSuppressesMeetMediaPermissionControl() {
  const documentListeners = [];
  const allowButton = {
    dataset: {},
    style: {},
    textContent: "Allow microphone and camera",
    getAttribute() {
      return null;
    }
  };

  const context = {
    chrome: {
      runtime: {
        onMessage: {
          addListener() {}
        }
      }
    },
    console,
    document: {
      addEventListener(type, listener, capture) {
        documentListeners.push({ type, listener, capture });
      },
      querySelectorAll() {
        return [allowButton];
      }
    },
    window: {
      addEventListener() {}
    }
  };

  vm.runInNewContext(
    fs.readFileSync(path.join(extensionDir, "content.js"), "utf8"),
    context
  );

  assert.equal(allowButton.dataset.orbitSuppressed, "allow-media");
  assert.equal(allowButton.style.display, "none");

  const clickListener = documentListeners.find(({ type }) => type === "click");
  assert.equal(clickListener.capture, true);

  const event = {
    prevented: false,
    propagationStopped: false,
    immediatePropagationStopped: false,
    target: {
      closest() {
        return allowButton;
      }
    },
    preventDefault() {
      this.prevented = true;
    },
    stopPropagation() {
      this.propagationStopped = true;
    },
    stopImmediatePropagation() {
      this.immediatePropagationStopped = true;
    }
  };
  clickListener.listener(event);

  assert.equal(event.prevented, true);
  assert.equal(event.propagationStopped, true);
  assert.equal(event.immediatePropagationStopped, true);
}

function testFrameChangeDetectorRequiresStableMeaningfulChange() {
  const context = {};
  vm.runInNewContext(
    fs.readFileSync(path.join(extensionDir, "frame_change.js"), "utf8"),
    context
  );

  const detector = context.OrbitFrameChange;
  const dark = new Uint8Array([0, 0, 0, 0]);
  const bright = new Uint8Array([255, 255, 255, 255]);
  const almostBright = new Uint8Array([254, 255, 254, 255]);

  assert.equal(
    detector.shouldSendFrame({
      current: bright,
      previousSample: dark,
      lastSent: dark,
      nowMs: 10000,
      lastSentAt: 0,
      cooldownMs: 8000
    }),
    false,
    "a changing transition must not be sent"
  );
  assert.equal(
    detector.shouldSendFrame({
      current: bright,
      previousSample: almostBright,
      lastSent: dark,
      nowMs: 10000,
      lastSentAt: 0,
      cooldownMs: 8000
    }),
    true,
    "a stable frame that differs from the last sent frame should be sent"
  );
  assert.equal(
    detector.shouldSendFrame({
      current: bright,
      previousSample: bright,
      lastSent: dark,
      nowMs: 12000,
      lastSentAt: 10000,
      cooldownMs: 8000
    }),
    false,
    "the VLM cooldown must suppress otherwise eligible frames"
  );
}

async function main() {
  await testToolbarActivationReportsStatus();
  testContentScriptDisplaysActiveStatus();
  testContentScriptSuppressesMeetMediaPermissionControl();
  testFrameChangeDetectorRequiresStableMeaningfulChange();
  console.log("Orbit meeting capture extension tests passed.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
