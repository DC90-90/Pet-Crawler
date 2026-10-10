import axios from "axios";

export function waitForReadRetry(signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new axios.CanceledError());
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new axios.CanceledError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, 5000);
    signal?.addEventListener("abort", abort, { once: true });
  });
}