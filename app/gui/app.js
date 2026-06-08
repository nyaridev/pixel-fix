const directoryInput = document.getElementById('directoryInput');
const browseBtn = document.getElementById('browseBtn');
const recursiveInput = document.getElementById('recursiveInput');
const threadInput = document.getElementById('threadInput');
const threadLabel = document.getElementById('threadLabel');
const imageList = document.getElementById('imageList');
const countText = document.getElementById('countText');
const clearBtn = document.getElementById('clearBtn');
const progress = document.getElementById('progress');
const startBtn = document.getElementById('startBtn');
const cancelBtn = document.getElementById('cancelBtn');
const statusText = document.getElementById('statusText');
const titleText = document.getElementById('titleText');
const appIcon = document.getElementById('appIcon');
const minimizeBtn = document.getElementById('minimizeBtn');
const closeBtn = document.getElementById('closeBtn');

let currentImages = [];
let pollTimer = null;
let renderToken = 0;
let isRunning = false;

const iconThemeQuery = window.matchMedia('(prefers-color-scheme: dark)');
syncAppIcon(iconThemeQuery);
if (iconThemeQuery.addEventListener) {
  iconThemeQuery.addEventListener('change', syncAppIcon);
} else {
  iconThemeQuery.addListener(syncAppIcon);
}

window.addEventListener('pywebviewready', async () => {
  const state = await window.pywebview.api.get_initial_state();
  applyState(state);
});

browseBtn.addEventListener('click', async () => {
  applyState(await window.pywebview.api.choose_directory(recursiveInput.checked));
});

recursiveInput.addEventListener('change', async () => {
  if (!directoryInput.value || directoryInput.value === 'Dropped files') return;
  applyState(await window.pywebview.api.scan_directory(directoryInput.value, recursiveInput.checked));
});

directoryInput.addEventListener('change', async () => {
  if (!directoryInput.value || directoryInput.value === 'Dropped files') return;
  applyState(await window.pywebview.api.scan_directory(directoryInput.value, recursiveInput.checked));
});

threadInput.addEventListener('input', updateThreadLabel);

startBtn.addEventListener('click', async () => {
  applyState(await window.pywebview.api.start(Number(threadInput.value)));
  startPolling();
});

cancelBtn.addEventListener('click', async () => {
  applyState(await window.pywebview.api.cancel());
});

clearBtn.addEventListener('click', async () => {
  applyState(await window.pywebview.api.clear_images());
});

if (minimizeBtn) {
  minimizeBtn.addEventListener('click', () => window.pywebview.api.minimize());
}

if (closeBtn) {
  closeBtn.addEventListener('click', () => window.pywebview.api.close());
}

document.addEventListener('dragenter', event => {
  event.preventDefault();
  document.body.classList.add('dragging');
});

document.addEventListener('dragover', event => {
  event.preventDefault();
  document.body.classList.add('dragging');
});

document.addEventListener('dragleave', event => {
  if (event.clientX <= 0 || event.clientY <= 0 ||
      event.clientX >= window.innerWidth || event.clientY >= window.innerHeight) {
    document.body.classList.remove('dragging');
  }
});

document.addEventListener('drop', async event => {
  event.preventDefault();
  document.body.classList.remove('dragging');
  const paths = Array.from(event.dataTransfer.files)
    .map(file => file.path || file.webkitRelativePath || '')
    .filter(isLikelyAbsolutePath);

  if (paths.length) {
    applyState(await window.pywebview.api.load_dropped_paths(paths, recursiveInput.checked));
  } else {
    statusText.textContent = 'Resolving dropped file paths...';
  }
});

window.pixelFixHandlePythonDrop = async paths => {
  document.body.classList.remove('dragging');
  applyState(await window.pywebview.api.load_dropped_paths(paths, recursiveInput.checked));
};

window.pixelFixHandleDropResolutionFailed = () => {
  document.body.classList.remove('dragging');
  statusText.textContent = 'Could not resolve dropped file paths. Use Browse if this keeps happening.';
};

function isLikelyAbsolutePath(path) {
  const normalized = path.replaceAll('\\', '/');
  return /^[A-Za-z]:\//.test(normalized) || normalized.startsWith('/');
}

function syncAppIcon(event) {
  if (!appIcon) return;
  appIcon.href = event.matches ? '../assets/icon-white.ico' : '../assets/icon.ico';
}

function applyState(state) {
  if (!state) return;
  if (state.appTitle) {
    document.title = state.appTitle;
    if (titleText) titleText.textContent = state.appTitle;
  }
  if (state.showCustomTitleBar === false) {
    document.body.classList.remove('with-titlebar');
    document.body.classList.add('native-titlebar');
  } else {
    document.body.classList.remove('native-titlebar');
    document.body.classList.add('with-titlebar');
  }
  if (state.directory !== undefined) directoryInput.value = state.directory || '';
  if (state.maxThreads) {
    threadInput.max = state.maxThreads;
    if (!threadInput.dataset.ready) {
      threadInput.value = state.defaultThreads || 1;
      threadInput.dataset.ready = '1';
    }
  }

  if (state.images) {
    currentImages = state.images;
    renderImages(currentImages);
  }

  setRunning(Boolean(state.running));
  updateThreadLabel();
  updateCount(state.imageCount ?? currentImages.length);
  updateProgress(state.progress);
  if (state.status) statusText.textContent = state.status;
}

function setRunning(running) {
  isRunning = running;
  browseBtn.disabled = running;
  recursiveInput.disabled = running;
  threadInput.disabled = running;
  directoryInput.disabled = running;
  startBtn.disabled = running;
  cancelBtn.disabled = !running;
  clearBtn.disabled = running || currentImages.length === 0;
}

function updateThreadLabel() {
  threadLabel.textContent = `Threads: ${threadInput.value} / ${threadInput.max}`;
}

function updateCount(count) {
  countText.textContent = count ? `${count} image${count === 1 ? '' : 's'}` : 'No images loaded';
  clearBtn.disabled = isRunning || count === 0;
}

function updateProgress(progressState) {
  const total = Math.max(progressState?.total || currentImages.length || 1, 1);
  progress.max = total;
  progress.value = progressState?.completed || 0;
}

function renderImages(images) {
  const token = ++renderToken;
  imageList.textContent = '';
  const chunkSize = 250;
  let index = 0;

  function renderChunk() {
    if (token !== renderToken) return;
    const fragment = document.createDocumentFragment();
    const end = Math.min(index + chunkSize, images.length);
    for (; index < end; index += 1) {
      const item = document.createElement('div');
      item.className = 'list-item';
      item.textContent = images[index].display;
      item.title = images[index].path;
      fragment.appendChild(item);
    }
    imageList.appendChild(fragment);
    if (index < images.length) requestAnimationFrame(renderChunk);
  }

  requestAnimationFrame(renderChunk);
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const state = await window.pywebview.api.poll();
    applyState({ ...state, images: undefined });
    if (!state.running) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }, 200);
}
