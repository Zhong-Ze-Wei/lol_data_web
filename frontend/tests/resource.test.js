import { effectScope, nextTick, ref } from "vue";
import { describe, expect, it } from "vitest";
import { useResource } from "../src/composables/useResource.js";

describe("异步页面数据", () => {
  it("搜索条件变化时取消旧请求，迟到的结果不会覆盖新页面", async () => {
    const selection = ref("A");
    const pending = [];
    const scope = effectScope();
    let resource;
    scope.run(() => {
      resource = useResource(
        (signal) => new Promise((resolve) => pending.push({ signal, resolve })),
        [selection],
      );
    });
    selection.value = "B";
    await nextTick();
    expect(pending[0].signal.aborted).toBe(true);
    pending[1].resolve({ name: "B" });
    await Promise.resolve();
    pending[0].resolve({ name: "A" });
    await Promise.resolve();
    expect(resource.data.value).toEqual({ name: "B" });
    expect(resource.loading.value).toBe(false);
    scope.stop();
  });
  it("退出页面会取消请求", () => {
    const scope = effectScope();
    let signal;
    scope.run(() =>
      useResource((current) => {
        signal = current;
        return new Promise(() => {});
      }),
    );
    scope.stop();
    expect(signal.aborted).toBe(true);
  });
});
