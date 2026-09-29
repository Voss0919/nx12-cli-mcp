using System;
using System.IO;
using System.Net.Sockets;

public class PipeClient
{
    public static int Main(string[] args)
    {
        if (args.Length < 3) { Console.Error.WriteLine("port, token and command required"); return 2; }
        try
        {
            using (TcpClient client = new TcpClient())
            {
                IAsyncResult pending = client.BeginConnect("127.0.0.1", int.Parse(args[0]), null, null);
                if (!pending.AsyncWaitHandle.WaitOne(2000)) throw new IOException("Local bridge timed out");
                client.EndConnect(pending);
                using (NetworkStream stream = client.GetStream())
                using (StreamReader reader = new StreamReader(stream))
                using (StreamWriter writer = new StreamWriter(stream))
                {
                    writer.AutoFlush = true;
                    writer.WriteLine(String.Join("\t", args, 1, args.Length - 1));
                    string answer = reader.ReadLine();
                    if (answer == null) throw new IOException("No response");
                    Console.WriteLine(answer);
                    return answer.StartsWith("OK\t") ? 0 : 1;
                }
            }
        }
        catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
    }
}
