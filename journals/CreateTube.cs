using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using NXOpen;
using NXOpen.Features;
using NXOpen.GeometricUtilities;

public class CreateTube
{
    public static void Main(string[] args)
    {
        try
        {
            if (args == null || args.Length != 4) throw new ArgumentException("output, outer_d, bore_d, height required");
            string path = Path.GetFullPath(args[0]);
            double outer = double.Parse(args[1], CultureInfo.InvariantCulture);
            double bore = double.Parse(args[2], CultureInfo.InvariantCulture);
            double height = double.Parse(args[3], CultureInfo.InvariantCulture);
            if (File.Exists(path)) throw new IOException("Output already exists: " + path);
            if (!(outer > bore && bore > 0 && height > 0)) throw new ArgumentException("Invalid dimensions");

            Session session = Session.GetSession();
            Part part = session.Parts.NewDisplay("CLI_Tube", Part.Units.Millimeters);
            CylinderBuilder outerBuilder = part.Features.CreateCylinderBuilder(null);
            outerBuilder.Type = CylinderBuilder.Types.AxisDiameterAndHeight;
            outerBuilder.Diameter.Value = outer;
            outerBuilder.Height.Value = height;
            outerBuilder.Origin = new Point3d(0, 0, 0);
            outerBuilder.Direction = new Vector3d(0, 0, 1);
            outerBuilder.BooleanOption.Type = BooleanOperation.BooleanType.Create;
            outerBuilder.CommitFeature();
            outerBuilder.Destroy();
            Body mainBody = part.Bodies.ToArray()[0];

            CylinderBuilder boreBuilder = part.Features.CreateCylinderBuilder(null);
            boreBuilder.Type = CylinderBuilder.Types.AxisDiameterAndHeight;
            boreBuilder.Diameter.Value = bore;
            boreBuilder.Height.Value = 3 * height;
            boreBuilder.Origin = new Point3d(0, 0, -height);
            boreBuilder.Direction = new Vector3d(0, 0, 1);
            boreBuilder.BooleanOption.Type = BooleanOperation.BooleanType.Create;
            boreBuilder.CommitFeature();
            boreBuilder.Destroy();
            Body toolBody = null;
            foreach (Body body in part.Bodies.ToArray()) if (body != mainBody) toolBody = body;
            if (toolBody == null) throw new Exception("Bore tool missing");
            bool nonAssociative, unparameterized;
            BooleanFeature[] cuts = part.Features.CreateSubtractFeature(mainBody, false,
                new Body[] { toolBody }, false, false, out nonAssociative, out unparameterized);
            if (cuts == null || cuts.Length == 0 || nonAssociative || unparameterized)
                throw new Exception("Associative subtract failed");
            if (part.Bodies.ToArray().Length != 1) throw new Exception("Expected one final body");
            part.SaveAs(path);
            if (!File.Exists(path)) throw new IOException("SaveAs did not create file");
            Console.WriteLine("CREATED=" + path);
            Console.WriteLine("RESULT: PASS");
        }
        catch (Exception e)
        {
            Console.WriteLine("ERROR=" + e);
            Console.WriteLine("RESULT: FAIL");
        }
    }

    public static int GetUnloadOption(string dummy) { return (int)Session.LibraryUnloadOption.Immediately; }
}
