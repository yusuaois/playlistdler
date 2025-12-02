console.log("Script loaded"); // Add this line at the beginning of script.js

const MAX_LOGS = 50;
let logBuffer = [];
let Interval;
let progressData = {
  current: 0,
  total: 0,
  percent: 0,
  curItem: null,
};

async function download() {
  const spotifyLink = document.getElementById("spotifyLink").value;

  if (!spotifyLink) {
    document.getElementById("result").innerText =
      "Please enter a Spotify link.";
    return;
  }

  // Clear previous logs and result
  const logsElement = document.getElementById("logs");
  logsElement.innerHTML = "";
  document.getElementById("result").innerText = "";

  progressData = {
    current: 0,
    total: 0,
    percent: 0,
    curItem: null,
  };

  // Show and reset the progress bar
  const progressBar = document.getElementById("progress");
  progressBar.style.display = "block";
  progressBar.value = 0;

  startLogRenderer(logsElement);

  // Create an EventSource to listen to the server-sent events
  const eventSource = new EventSource(
    `/download?spotify_link=${encodeURIComponent(spotifyLink)}`
  );

  eventSource.onmessage = function (event) {
    const log = event.data;

    if (log.includes("Downloading item") && log.includes("of")) {
      // [download] Downloading item 145 of 357
      // Download link received, set progress to 100%
      const match = log.match(/item\s+(\d+)\s+of\s+(\d+)/i);
      if (match) {
        progressData.current = parseInt(match[1]);
        progressData.total = parseInt(match[2]);
        progressData.curItem = log;
        updateProgressDisplay();
      }
    } else if (log.startsWith("✅ DOWNLOAD:")) {
      progressBar.value = 100;
      const path = log.split("✅ DOWNLOAD: ")[1].trim();
      console.log("Download path:", path);

      const downloadLink = document.createElement("a");
      downloadLink.href = `/downloads/${path}`;
      downloadLink.download = decodeURIComponent(path.split("/").pop());
      downloadLink.innerText = "Click to download your file";
      document.getElementById("result").appendChild(downloadLink);
      downloadLink.click();

      eventSource.close();
      setTimeout(() => {
        progressBar.style.display = "none";
      }, 3000);
      stopLogRenderer();
    } else if (
      log.includes("Download completed") ||
      log.includes("Download process completed successfully")
    ) {
      // Show a success message in logs
      logBuffer.push("✅ All files processing completed.");
    } else if (log.startsWith("Error") || log.includes("Error:")) {
      // Display error message and close EventSource
      document.getElementById("result").innerText = `Error: ${log}`;
      eventSource.close();
      stopLogRenderer();
    } else {
      logBuffer.push(log);
    }
  };

  eventSource.onerror = function () {
    // Only show error if no success message was received
    if (!logsElement.innerText.includes("processing completed")) {
      document.getElementById("result").innerText =
        "Status: Connection closed.";
    }
    eventSource.close();
    stopLogRenderer();
    setTimeout(() => {
      progressBar.style.display = "none";
    }, 3000);
  };
}

function updateProgressDisplay() {
  if (progressData.total > 0) {
    const percent = Math.round(
      (progressData.current / progressData.total) * 100
    );
    progressData.percent = percent;
    const progressBar = document.getElementById("progress");
    progressBar.value = percent;
  }
}

function startLogRenderer(container) {
  if (Interval) clearInterval(Interval);

  Interval = setInterval(() => {
    if (logBuffer.length === 0) return;

    // Create document fragment in memory for performance
    const fragment = document.createDocumentFragment();
    const logsToRender = [...logBuffer];
    logBuffer = []; // Clear buffer
    logsToRender.forEach((text) => {
      const p = document.createElement("div");
      p.textContent = text;

      fragment.appendChild(p);
    });
    // Add to page at once, triggering only one reflow
    container.appendChild(fragment);
    // Batch cleanup of old logs
    while (container.children.length > MAX_LOGS) {
      container.removeChild(container.firstElementChild);
    }
    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
  }, 100);
}

function stopLogRenderer() {
  setTimeout(() => {
    if (Interval) clearInterval(Interval);
  }, 500);
}

// Function to handle the Admin / Log Out button behavior
function handleAdminButton() {
  if (document.getElementById("adminButton").innerText === "Admin") {
    showLoginModal(); // Show login modal if not logged in
  } else {
    logout(); // Log out if already logged in
  }
}

// Show login modal
function showLoginModal() {
  document.getElementById("loginModal").classList.add("show"); // Show modal on button click
}

// Hide login modal
function closeLoginModal() {
  document.getElementById("loginModal").classList.remove("show"); // Hide modal when closed
}

// Check login status, toggle button text, and show/hide admin message

async function checkLoginStatus() {
  try {
    const response = await fetch("/check-login");
    const data = await response.json();
    const adminButton = document.getElementById("adminButton");
    const adminMessage = document.getElementById("adminMessage");
    const adminControls = document.getElementById("adminControls");

    if (data.loggedIn) {
      adminButton.innerText = "Log Out";
      adminMessage.style.display = "block";
      adminControls.style.display = "block";
    } else {
      adminButton.innerText = "Admin";
      adminMessage.style.display = "none";
      adminControls.style.display = "none";
    }
  } catch (e) {
    console.error("Error checking login status:", e);
  }
}

async function logout() {
  await fetch("/logout", { method: "POST" });
  await checkLoginStatus();
}

// After successful login, change button text to "Log Out" and show the message

async function login() {
  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;

  const response = await fetch("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  const data = await response.json();
  const loginMessageElement = document.getElementById("loginMessage");

  if (data.success) {
    loginMessageElement.innerText = "Login successful!";
    closeLoginModal();
    await checkLoginStatus();
  } else {
    loginMessageElement.innerText = "Login failed. Try again.";
  }
}

async function setDownloadPath() {
  const path = document.getElementById("downloadPath").value;
  const messageDiv = document.getElementById("pathMessage");

  if (!path) {
    messageDiv.innerText = "Path cannot be empty.";
    return;
  }

  const response = await fetch("/set-download-path", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });

  const data = await response.json();

  if (data.success) {
    messageDiv.innerText = `Download path set successfully to: ${data.new_path}`;
    messageDiv.style.color = "lime";
  } else {
    messageDiv.innerText = `Error: ${data.message}`;
    messageDiv.style.color = "red";
  }
}

// Call checkLoginStatus on page load to set initial button state and message visibility
window.onload = checkLoginStatus;
