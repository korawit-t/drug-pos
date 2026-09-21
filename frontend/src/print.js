// Prints a Django print page through a hidden iframe. With Chrome started as
// --kiosk-printing this goes straight to the default printer, no dialog.
export function printPage(url) {
  return new Promise((resolve) => {
    const frame = document.createElement('iframe');
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;';
    const cleanup = () => setTimeout(() => frame.remove(), 500);
    frame.onload = () => {
      const win = frame.contentWindow;
      win.addEventListener('afterprint', cleanup);
      setTimeout(cleanup, 60000);
      win.focus();
      win.print();
      resolve();
    };
    frame.src = url;
    document.body.appendChild(frame);
  });
}

export const receiptUrl = (saleId) => `/print/receipt/${saleId}/`;
export const labelsUrl = (saleId) => `/print/labels/${saleId}/`;
