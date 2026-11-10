// Local previews only. Uploads persist through the existing profile form submission.
(() => {
  for (const name of ['logo', 'cover_image', 'photo']) {
    const input = document.getElementById(`id_${name}`);
    if (!input) continue;
    const images = [...document.querySelectorAll(`[data-image-preview="${name}"]`)];
    const fallbacks = [...document.querySelectorAll(`[data-image-fallback="${name}"]`)];
    const originals = images.map(image => image.getAttribute('src') === image.dataset.defaultSrc ? '' : (image.getAttribute('src') || ''));
    const clear = document.querySelector(`[name="${name}-clear"]`);
    let objectUrl;
    const refresh = () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null;
      const file = input.files[0];
      if (file && ['image/jpeg', 'image/png', 'image/webp'].includes(file.type) && file.size <= 5 * 1024 * 1024) {
        objectUrl = URL.createObjectURL(file);
      }
      images.forEach((image, index) => {
        const src = objectUrl || (clear?.checked ? '' : originals[index]);
        const displayed = src || image.dataset.defaultSrc || '';
        image.hidden = !displayed;
        if (displayed) image.src = displayed;
        else image.removeAttribute('src');
      });
      fallbacks.forEach(node => {
        node.hidden = Boolean(objectUrl || (!clear?.checked && originals[0]));
      });
    };
    document.querySelectorAll(`[data-image-edit="${name}"]`).forEach(button => {
      button.hidden = false;
      button.addEventListener('click', () => input.click());
    });
    input.addEventListener('change', () => {
      if (input.files.length && clear) clear.checked = false;
      refresh();
    });
    clear?.addEventListener('change', () => {
      if (clear.checked) input.value = '';
      refresh();
    });
    window.addEventListener('pagehide', () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    });
  }
})();
