import { onScopeDispose, ref, shallowRef, watch } from "vue";

export function useResource(loader, dependencies = []) {
  const data = shallowRef(null);
  const loading = ref(false);
  const error = ref("");
  let controller;
  let generation = 0;

  async function reload() {
    controller?.abort();
    controller = new AbortController();
    const current = ++generation;
    loading.value = true;
    error.value = "";
    data.value = null;
    try {
      const result = await loader(controller.signal);
      if (current === generation) data.value = result;
    } catch (cause) {
      if (current === generation && cause.name !== "AbortError")
        error.value = cause.message;
    } finally {
      if (current === generation) loading.value = false;
    }
  }

  watch(dependencies, reload, { immediate: true });
  onScopeDispose(() => {
    generation++;
    controller?.abort();
  });
  return { data, loading, error, reload };
}
