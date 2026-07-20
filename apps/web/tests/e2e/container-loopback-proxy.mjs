import net from "node:net";


const forwards = [
  { listenPort: 3000, targetHost: "web-test", targetPort: 3000 },
  { listenPort: 8081, targetHost: "keycloak", targetPort: 8080 }
];

for (const forward of forwards) {
  const server = net.createServer((source) => {
    const target = net.createConnection({ host: forward.targetHost, port: forward.targetPort });
    source.pipe(target);
    target.pipe(source);
    const close = () => {
      source.destroy();
      target.destroy();
    };
    source.on("error", close);
    target.on("error", close);
  });
  server.listen(forward.listenPort, "::");
}
