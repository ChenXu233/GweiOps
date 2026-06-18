export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-between p-24">
      <div className="z-10 max-w-5xl w-full items-center justify-between font-mono text-sm lg:flex">
        <h1 className="text-4xl font-bold">既未 · Gwei</h1>
        <p className="text-xl text-gray-600">AI 负责完成，人类负责决定。</p>
      </div>

      <div className="mb-32 grid text-center lg:max-w-5xl lg:w-full lg:mb-0 lg:grid-cols-3 lg:text-left">
        <div className="group rounded-lg border border-transparent px-5 py-4 transition-colors hover:border-gray-300 hover:bg-gray-100">
          <h2 className="mb-3 text-2xl font-semibold">Issue 分析</h2>
          <p className="m-0 max-w-[30ch] text-sm opacity-50">
            自动分析 Issue，生成标签，检测重复
          </p>
        </div>

        <div className="group rounded-lg border border-transparent px-5 py-4 transition-colors hover:border-gray-300 hover:bg-gray-100">
          <h2 className="mb-3 text-2xl font-semibold">Patch 生成</h2>
          <p className="m-0 max-w-[30ch] text-sm opacity-50">
            生成三种修复方案，供开发者选择
          </p>
        </div>

        <div className="group rounded-lg border border-transparent px-5 py-4 transition-colors hover:border-gray-300 hover:bg-gray-100">
          <h2 className="mb-3 text-2xl font-semibold">PR 自动化</h2>
          <p className="m-0 max-w-[30ch] text-sm opacity-50">
            自动创建 PR，处理投票和审查
          </p>
        </div>
      </div>
    </main>
  )
}
