module.exports = {
  devServer: {
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        // pathRewrite: { '^/api': '/api' } // 不改路径可以省略
      }
    }
  },
  outputDir: '../app/static/dist',
  assetsDir: 'static'
};
