const envList = [
  {
    envVersion: "develop",
    apiBase: "http://127.0.0.1:3000",
  },
  {
    envVersion: "trial",
    apiBase: "https://api.your-domain.com",
  },
  {
    envVersion: "release",
    apiBase: "https://api.your-domain.com",
  },
];
const isMac = false;
module.exports = {
  envList,
  isMac
};
