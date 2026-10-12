// ASTRA browser extension - popup
//
// A single button that toggles whether the pages the user visits are streamed
// to the local ASTRA agent. No page data is ever shown here.

const button = document.getElementById("integrate");
const statusEl = document.getElementById("status");
const endpointEl = document.getElementById("endpoint");

let enabled = false;

function apply(state) {
  if (!state) return;
  enabled = !!state.enabled;
  endpointEl.textContent = state.endpoint || "";

  if (enabled) {
    button.textContent = "ASTRA is integrated \u2014 click to stop";
    button.classList.add("on");
  } else {
    button.textContent = "Integrate ASTRA with webpages";
    button.classList.remove("on");
  }

  const status = state.status;
  if (!status) {
    statusEl.textContent = "";
    statusEl.className = "";
  } else if (status.ok) {
    statusEl.textContent = enabled ? "Connected to ASTRA." : "Disconnected from ASTRA.";
    statusEl.className = "ok";
  } else {
    statusEl.textContent = `Could not reach ASTRA: ${status.message}`;
    statusEl.className = "err";
  }
}

async function refresh() {
  try {
    apply(await browser.runtime.sendMessage({ type: "get-integration" }));
  } catch (err) {
    statusEl.textContent = `Extension error: ${err}`;
    statusEl.className = "err";
  }
}

button.addEventListener("click", async () => {
  button.disabled = true;
  try {
    apply(await browser.runtime.sendMessage({ type: "set-integration", enabled: !enabled }));
  } catch (err) {
    statusEl.textContent = `Extension error: ${err}`;
    statusEl.className = "err";
  } finally {
    button.disabled = false;
  }
});

refresh();
