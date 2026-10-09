const { apiOrigin, canonical } = require('./receipt.cjs');

class BuildReceiptPlugin {
  constructor(receipt, revalidate) {
    this.receipt = receipt;
    this.revalidate = revalidate;
  }
  apply(compiler) {
    const name = 'DaleelBuildReceipt';
    compiler.hooks.thisCompilation.tap(name, compilation => {
      compilation.hooks.processAssets.tap({ name, stage: compiler.webpack.Compilation.PROCESS_ASSETS_STAGE_REPORT }, () => {
        if (canonical(this.revalidate()) !== canonical(this.receipt)) {
          throw Error('Frontend inputs changed during compilation; rebuild from stable inputs');
        }
        const values = compiler.options.plugins
          .map(p => p.definitions && p.definitions['process.env'])
          .filter(Boolean).map(d => d.REACT_APP_BACKEND_URL).filter(v => v !== undefined);
        // CRA omits an unset variable, but defines an empty one as "". Both
        // compile to the API client's same-origin fallback and must agree with
        // the receipt. Duplicate/conflicting definitions still fail closed.
        const compiledOrigin = values.length === 1
          ? apiOrigin({ REACT_APP_BACKEND_URL: JSON.parse(values[0]) }) : null;
        if (values.length > 1 || compiledOrigin !== this.receipt.api_origin) {
          throw Error('Compiled API origin differs from frontend build receipt');
        }
        compilation.emitAsset('build-provenance.json', new compiler.webpack.sources.RawSource(JSON.stringify(this.receipt, null, 2) + '\n'));
      });
    });
  }
}
module.exports = { BuildReceiptPlugin };