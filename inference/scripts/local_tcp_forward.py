"""Forward a localhost TCP port to another localhost port."""
import argparse,asyncio,logging
p=argparse.ArgumentParser();p.add_argument('--listen-port',type=int,required=True);p.add_argument('--target-port',type=int,required=True);args=p.parse_args()
async def pipe(reader,writer):
 try:
  while data:=await reader.read(65536):writer.write(data);await writer.drain()
  if writer.can_write_eof():writer.write_eof()
 except (ConnectionError,OSError):pass
async def handle(reader,writer):
 try:
  upstream_read,upstream_write=await asyncio.open_connection('127.0.0.1',args.target_port)
  try:await asyncio.gather(pipe(reader,upstream_write),pipe(upstream_read,writer))
  finally:upstream_write.close();await upstream_write.wait_closed()
 except (ConnectionError,OSError) as exc:logging.warning('upstream connection failed: %s',exc)
 finally:writer.close();await writer.wait_closed()
async def main():
 server=await asyncio.start_server(handle,'127.0.0.1',args.listen_port);logging.warning('127.0.0.1:%d -> 127.0.0.1:%d',args.listen_port,args.target_port)
 async with server:await server.serve_forever()
asyncio.run(main())
