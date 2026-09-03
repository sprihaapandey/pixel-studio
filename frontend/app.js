const factorSlider = document.getElementById('factorSlider');
const factorValue = document.getElementById('factorValue');
const imageInput = document.getElementById('imageInput');
const outputImage = document.getElementById('outputImage');
const saveButton = document.getElementById('saveButton');
let uploadReady = false;
let previewTimer = null;

function setStatus(message) {
  // status display removed; keep function for compatibility.
}

function setPlaceholder() {
  outputImage.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400"><rect width="100%" height="100%" fill="#0f172a"/><text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" fill="#94a3b8" font-size="28" font-family="Arial">Upload an image to preview</text></svg>'
  );
  saveButton.classList.add('hidden');
  saveButton.disabled = true;
}

function refreshPreview() {
  const factor = factorSlider.value;
  factorValue.textContent = factor;

  if (!uploadReady || imageInput.files.length === 0) {
    saveButton.classList.add('hidden');
    setPlaceholder();
    return;
  }

  saveButton.classList.add('hidden');
  outputImage.src = '/api/preview?factor=' + factor + '&t=' + Date.now();
}

function schedulePreview() {
  if (previewTimer) {
    clearTimeout(previewTimer);
  }

  previewTimer = setTimeout(() => {
    refreshPreview();
  }, 90);
}

outputImage.addEventListener('load', function () {
  if (!outputImage.src || outputImage.src.startsWith('data:image/svg+xml')) {
    saveButton.classList.add('hidden');
    saveButton.disabled = true;
    return;
  }

  saveButton.classList.remove('hidden');
  saveButton.disabled = false;
});

outputImage.addEventListener('error', function () {
  saveButton.classList.add('hidden');
  saveButton.disabled = true;
});

saveButton.addEventListener('click', function () {
  if (!outputImage.src || outputImage.src.startsWith('data:image/svg+xml')) {
    return;
  }

  const link = document.createElement('a');
  link.href = outputImage.src;
  link.download = 'pixel-art-conversion.png';
  document.body.appendChild(link);
  link.click();
  link.remove();
});

factorSlider.disabled = true;
uploadReady = false;
saveButton.disabled = true;
saveButton.classList.add('hidden');
setPlaceholder();

imageInput.addEventListener('change', function () {
  if (!imageInput.files.length) {
    factorSlider.disabled = true;
    uploadReady = false;
    setStatus('Waiting for image');
    setPlaceholder();
    return;
  }

  const formData = new FormData();
  formData.append('image', imageInput.files[0]);
  setStatus('Uploading and quantizing image...');

  fetch('/api/upload', {
    method: 'POST',
    body: formData
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error('Upload failed');
      }
      uploadReady = true;
      factorSlider.disabled = false;
      refreshPreview();
    })
    .catch(() => {
      uploadReady = false;
      factorSlider.disabled = true;
      saveButton.disabled = true;
      saveButton.classList.add('hidden');
      setPlaceholder();
    });
});

factorSlider.addEventListener('input', function () {
  if (!uploadReady || imageInput.files.length === 0) {
    return;
  }
  schedulePreview();
});
