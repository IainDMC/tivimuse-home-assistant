class TiviMuseSettings extends HTMLElement {
  set hass(hass) {
    if (this.started) return;
    this.started = true;
    this.textContent = "Opening TiviMuse settings…";
    const entry = new URLSearchParams(location.search).get("entry");
    if (!entry || !/^[a-zA-Z0-9_-]+$/.test(entry)) {
      this.textContent = "Open this page from your TiviMuse device.";
      return;
    }
    hass.callWS({type: "auth/sign_path", path: "/api/tivimuse/web_manager/" + entry, expires: 30})
      .then(({path}) => location.replace(path))
      .catch(() => { this.textContent = "Could not open TiviMuse settings. Try the device link again."; });
  }
}
customElements.define("tivimuse-settings", TiviMuseSettings);
