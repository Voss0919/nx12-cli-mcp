using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using NXOpen;
using NXOpen.Features;
using NXOpen.GeometricUtilities;

public class LivePipe
{
    static Session session;
    static Part current;
    static Body stock;
    static double stockHeight;
    static double outerDiameter;
    static bool stop;
    static string outputRoot;
    static string secret;

    public static void Main(string[] args)
    {
        if (args == null || args.Length != 3) throw new ArgumentException("port, secret, output root required");
        int port = int.Parse(args[0], CultureInfo.InvariantCulture);
        secret = args[1];
        outputRoot = Path.GetFullPath(args[2]).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        Directory.CreateDirectory(outputRoot);
        session = Session.GetSession();
        TcpListener listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        Console.WriteLine("LIVE_BRIDGE_READY=" + port);
        try
        {
            while (!stop)
            {
                using (TcpClient client = listener.AcceptTcpClient())
                using (NetworkStream stream = client.GetStream())
                using (StreamReader reader = new StreamReader(stream))
                using (StreamWriter writer = new StreamWriter(stream))
                {
                    writer.AutoFlush = true;
                    try { writer.WriteLine(Handle(reader.ReadLine())); }
                    catch (Exception error) { writer.WriteLine("ERROR\t" + error.GetType().Name + ": " + error.Message.Replace('\n', ' ')); }
                }
            }
        }
        finally { listener.Stop(); }
        Console.WriteLine("LIVE_BRIDGE_STOPPED");
    }

    static string Handle(string line)
    {
        if (line == null) throw new ArgumentException("Empty command");
        string[] fields = line.Split('\t');
        if (fields.Length < 2 || fields[0] != secret) throw new UnauthorizedAccessException("Invalid local bridge token");
        string command = fields[1];
        if (command == "PING") return "OK\t" + Process.GetCurrentProcess().Id + "\t" + (current == null ? "NO_PART" : current.Name);
        if (command == "CREATE")
        {
            if (fields.Length != 4) throw new ArgumentException("CREATE requires outer diameter and height");
            if (current != null) throw new InvalidOperationException("A part is already active");
            double outer = Parse(fields[2], 2, 300), height = Parse(fields[3], 1, 500);
            stockHeight = height;
            outerDiameter = outer;
            current = session.Parts.NewDisplay("LIVE_TUBE", Part.Units.Millimeters);
            CylinderBuilder builder = current.Features.CreateCylinderBuilder(null);
            builder.Type = CylinderBuilder.Types.AxisDiameterAndHeight;
            builder.Diameter.Value = outer;
            builder.Height.Value = height;
            builder.Origin = new Point3d(0, 0, 0);
            builder.Direction = new Vector3d(0, 0, 1);
            builder.BooleanOption.Type = BooleanOperation.BooleanType.Create;
            builder.CommitFeature(); builder.Destroy();
            stock = current.Bodies.ToArray()[0];
            return Info();
        }
        if (command == "BORE")
        {
            if (fields.Length != 3) throw new ArgumentException("BORE requires diameter");
            if (current == null || stock == null) throw new InvalidOperationException("CREATE first");
            double bore = Parse(fields[2], 1, 299);
            if (bore >= outerDiameter) throw new ArgumentException("Bore must be smaller than stock");
            double height = stockHeight;
            CylinderBuilder builder = current.Features.CreateCylinderBuilder(null);
            builder.Type = CylinderBuilder.Types.AxisDiameterAndHeight;
            builder.Diameter.Value = bore;
            builder.Height.Value = height * 3;
            builder.Origin = new Point3d(0, 0, -height);
            builder.Direction = new Vector3d(0, 0, 1);
            builder.BooleanOption.Type = BooleanOperation.BooleanType.Create;
            builder.CommitFeature(); builder.Destroy();
            Body tool = null;
            foreach (Body body in current.Bodies.ToArray()) if (body != stock) tool = body;
            if (tool == null) throw new Exception("Bore tool missing");
            bool nonAssoc, unparam;
            BooleanFeature[] result = current.Features.CreateSubtractFeature(
                stock, false, new Body[] { tool }, false, false, out nonAssoc, out unparam);
            if (result == null || result.Length == 0 || nonAssoc || unparam) throw new Exception("Subtract failed");
            return Info();
        }
        if (command == "INFO") return Info();
        if (command == "SAVE")
        {
            if (fields.Length != 3 || current == null) throw new ArgumentException("SAVE requires active part and path");
            string path = Path.GetFullPath(fields[2]);
            if (!path.StartsWith(outputRoot, StringComparison.OrdinalIgnoreCase) ||
                !path.EndsWith(".prt", StringComparison.OrdinalIgnoreCase) || File.Exists(path))
                throw new IOException("Only new .prt files under the live output directory are allowed");
            current.SaveAs(path);
            if (!File.Exists(path)) throw new IOException("SaveAs failed");
            return "OK\t" + Process.GetCurrentProcess().Id + "\t" + path;
        }
        if (command == "STOP") { stop = true; return "OK\tSTOPPED"; }
        throw new ArgumentException("Unknown command");
    }

    static double Parse(string text, double min, double max)
    {
        double number = double.Parse(text, CultureInfo.InvariantCulture);
        if (Double.IsNaN(number) || Double.IsInfinity(number) || number < min || number > max)
            throw new ArgumentException("Dimension outside allowed range");
        return number;
    }

    static string Info()
    {
        if (current == null) return "OK\t" + Process.GetCurrentProcess().Id + "\tNO_PART";
        Body[] bodies = current.Bodies.ToArray();
        int features = current.Features.ToArray().Length;
        double volume = 0;
        if (bodies.Length > 0)
        {
            Unit area = null, cubic = null, mass = null, length = null;
            foreach (Unit unit in current.UnitCollection)
            {
                if (unit.TypeName == "SquareMilliMeter") area = unit;
                if (unit.TypeName == "CubicMilliMeter") cubic = unit;
                if (unit.TypeName == "Kilogram") mass = unit;
                if (unit.TypeName == "MilliMeter") length = unit;
            }
            List<IBody> list = new List<IBody>();
            foreach (Body body in bodies) list.Add(body);
            volume = current.MeasureManager.NewMassProperties(
                new Unit[] { area, cubic, mass, length }, 0.9999, list.ToArray()).Volume;
        }
        return "OK\t" + Process.GetCurrentProcess().Id + "\t" + current.Name + "\t" +
            bodies.Length + "\t" + features + "\t" + volume.ToString("R", CultureInfo.InvariantCulture);
    }

    public static int GetUnloadOption(string dummy) { return (int)Session.LibraryUnloadOption.Immediately; }
}
