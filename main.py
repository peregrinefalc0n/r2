import os
import random
import io
import discord
import subprocess
import requests
import asyncio
import constants
from discord.ext import commands
from pydub import AudioSegment
from queue import Queue
from discord.ext.commands import Bot
from discord.ext.commands import MissingRequiredArgument

#Right now hanging channels is not working, also using !stop and !play <station> again is kind of working with a global variable as a stopgap testing option rn.

channel_urls = {
    "chill": "https://r2extra.err.ee/r2chill",
    "pop" : "https://r2extra.err.ee/r2pop",
    "rap" : "https://r2extra.err.ee/r2p",
    "rock" : "https://r2extra.err.ee/r2rock",
    "alt" : "https://r2extra.err.ee/r2alternatiiv",
    "eesti" : "https://r2extra.err.ee/r2eesti"
}

channel_ids = {
    "chill": "r2chill",
    "pop" : "r2pop",
    "rap" : "r2p",
    "rock" : "r2rock",
    "alt" : "r2alt",
    "eesti" : "r2eesti"
}


# Define the intents you need
intents = discord.Intents.default()
intents.messages = True  # Enable GUILD_MESSAGE_CONTENT intent
intents.message_content = True

# Create a bot instance with the specified intents
bot = Bot(command_prefix='!', intents=intents)

# Create a queue for audio segments
audio_queue = Queue()
stop_requests = False


#return random 64 bytes as session id
def generate64Bytes():
    return random.randbytes(64)

# Define a check that will only allow a command to run if the message contains a specific keyword
def keywordCheck(keyword):
    def predicate(ctx):
        return keyword in ctx.message.content
    return commands.check(predicate)


def getStreamLinks(channel, server = "sb", short = "true"):

    #jsut for info, this is what we are recieving and parsing, server name can differ tho (lonestarr is just one of them)
    #EXTM3U
    #EXT-X-VERSION:3
    #EXT-X-STREAM-INF:PROGRAM-ID=1,CLOSED-CAPTIONS=NONE,BANDWIDTH=128000,CODECS="mp4a.40.2"
    #https://lonestarr.err.ee/live/r2alt/index.m3u8?id=47856552544348&short=true
    #EXT-X-STREAM-INF:PROGRAM-ID=1,CLOSED-CAPTIONS=NONE,BANDWIDTH=64000,CODECS="mp4a.40.2"
    #https://lonestarr.err.ee/live/r2altmadal/index.m3u8?id=47856552544348&short=true
    #EXT-X-STREAM-INF:PROGRAM-ID=1,CLOSED-CAPTIONS=NONE,BANDWIDTH=256000,CODECS="mp4a.40.2"
    #https://lonestarr.err.ee/live/r2altkorge/index.m3u8?id=47856552544348&short=true

    #it seems that sb server is always used for getting the first stream server links
    #https://sb.err.ee/live/r2chill.m3u8?short=true

    url = f"https://{server}.err.ee/live/{channel_ids[channel]}.m3u8?short={short}"
    extmu_info = requests.get(url).content.decode().split('\n')

    links = {
        "stream_64_link" : extmu_info[5],
        "stream_128_link" : extmu_info[3],
        "stream_256_link" : extmu_info[7]
    }
    
    return links


def getNextAudioFile(urls):

    url = urls.get("stream_128_link")

    #extm3u_data = requests.get(url).content.decode().split('\n')

    extmu_file_info = requests.get(url).content.decode().split('\n')

    #EXTM3U
    #EXT-X-VERSION:3
    #EXT-X-MEDIA-SEQUENCE:6583492
    #EXT-X-TARGETDURATION:10
    #EXTINF:10.005,
    #1697544796220.ts
    #EXTINF:10.005,
    #1697544806277.ts
    #EXTINF:9.984,
    #1697544816196.ts

    file_names = {
        "stream_64_filename" : extmu_file_info[7],
        "stream_128_filename" : extmu_file_info[5],
        "stream_256_filename" : extmu_file_info[9]
    }

    server = urls.get('stream_128_link').split('.')[0]
    station = urls.get('stream_128_link').split('.')[2].split("/")[2]
    filename = file_names.get('stream_128_filename')

    audio_file_request = requests.get(f"{server}.err.ee/live/{station}/{filename}")

    length_128_float = float(extmu_file_info[4].split(":")[1].strip(","))

    return (audio_file_request.content, length_128_float, filename)


def getCurrentSongName(channel):
    rds_url = f"https://services.err.ee/api/rds/getForChannel?channel={channel_ids[channel]}"
    rds_response = requests.get(rds_url)
    
    # Check if the request was successful (status code 200)
    if rds_response.status_code == 200:
        rds_data = rds_response.json()
        
        # Access the 'rds' value from the JSON response
        rds_value = rds_data.get('rds')
        
        return rds_value
    else:
        print(f"Request to {rds_url} failed with status code {rds_response.status_code}")
        return None


def convertToMp3(infile):
    
    outfile = f"{infile.split('.')[0]}.mp3"
    print("Outfile will be named:", outfile)

    subprocess.run(['ffmpeg', '-i', infile, outfile])
    return outfile


async def playAudio(queue, voice_client, channel):
    try:
        #await asyncio.sleep(12)
        while not queue.empty():
            
            global stop_requests
            if stop_requests:
                stop_requests = False
                break
            
            print("[GOOD] Queue not empty, taking next mp3 file and playing it.")

            #check for new song name
            song_name = getCurrentSongName(channel)
            await bot.change_presence(activity=discord.Game(name=song_name))
            print(f"[GOOD] Currently playing [{song_name}] on channel [{channel}].")

            audio_data = queue.get()

            mp3_file_name = audio_data[2]
            track_time = audio_data[1]
            track_data = audio_data[0]
            
            try:
                audio_source = await discord.FFmpegOpusAudio.from_probe(mp3_file_name, method='fallback')
            except Exception:
                continue

            async def playFile(voice_client, audio_source, mp3_file_name):
                
                # Play the audio source
                #await asyncio.sleep(track_time)
                voice_client.play(audio_source, after=lambda e: print(f"[GOOD] Done playing: {mp3_file_name}"))
                

            if audio_source:
                await playFile(voice_client, audio_source, mp3_file_name)
                print("[GOOD] Done with await playFile.")
                await asyncio.sleep(track_time)

                os.remove(mp3_file_name)
                print(f"[GOOD] Removed temp file: {mp3_file_name}")
            else:
                print("[ISSUE] Audio source is None. Skipping this segment.")
        else:
            print("[ISSUE] Queue was empty.")
    except Exception as e:
        print(f"[ISSUE] An error occurred while playing audio: {e}")


#unused
async def createOpusAudioSource(audio_data):
    try:
        # Use FFmpeg to convert the input audio data to Opus format
        process = await asyncio.create_subprocess_exec(
            'ffmpeg',             # FFmpeg executable
            '-f', 'mp2t',        # Specify the format as signed 16-bit little-endian
            '-ar', '128000',       # Sample rate (adjust as needed)
            '-ac', '2',           # Number of audio channels
            '-i', '-',             # Read from standard input
            '-f', 'opus',         # Output format as Opus
            '-'                   # Write to standard output
        )

        opus_audio_data, _ = await process.communicate(input=audio_data)

        if opus_audio_data:
            # Create a Discord audio source from the Opus audio data
            audio_source = discord.FFmpegOpusAudio.from_probe(io.BytesIO(opus_audio_data))
            return audio_source
        else:
            print("[ISSUE] FFmpeg conversion failed.")
            return None
    except Exception as e:
        print(f"[ISSUE] An error occurred while creating Opus audio source: {e}")
        return None


#unused
def convertToMp3WithoutFiles(input_data):
    try:
        # Use FFmpeg to convert the input audio data to MP3 format
        process = subprocess.Popen([
            'ffmpeg',             # FFmpeg executable
            '-f', 'ts',         # Specify the input format as MP3
            '-i', '-',            # Read from standard input
            '-f', 'mp3',         # Output format as MP3
            '-'],                # Write to standard output
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Pass the input data to FFmpeg's standard input
        output, errors = process.communicate(input=input_data)

        if process.returncode == 0:
            # Return the converted audio data
            return output
        else:
            print(f"FFmpeg conversion failed with errors: {errors.decode()}")
            return None
    except Exception as e:
        print(f"An error occurred while converting to MP3: {e}")
        return None


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot.change_presence(activity=discord.Game(name="Try !helpme"))


@bot.command()
@keywordCheck("now")
async def now(ctx):

    embed = discord.Embed(title="What's playin' rn", colour=discord.Colour(0xADD8E6))

    for channel in channel_ids.keys():
        song_name = getCurrentSongName(channel)
        embed.add_field(name=f"{channel.capitalize()}", value=f"{song_name}", inline=False)
        await asyncio.sleep(0.11)

    await ctx.send(embed=embed)

@bot.command()
@keywordCheck("helpme")
async def helpme(ctx):
    embed = discord.Embed(title="List of commands", colour=discord.Colour(0xADD8E6))

    embed.add_field(name=f"!help", value="See this message.", inline=False)
    embed.add_field(name=f"!join", value="Join the voice channel.", inline=False)
    embed.add_field(name=f"!leave", value="Leave the voice channel.", inline=False)
    embed.add_field(name=f"!play <channel>", value="Play audio from a specific channel.", inline=False)
    embed.add_field(name=f"!stop", value="Stop audio playback.", inline=False)
    embed.add_field(name=f"!now", value="Overview of each song currently playing.", inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
@keywordCheck("join")
async def join(ctx):
    # Check if the command author is in a voice channel
    if ctx.author.voice:
        voice_channel = ctx.author.voice.channel
        voice_client = await voice_channel.connect()
        await ctx.send("Genres: chill, pop, rap, rock, alt, eesti.")
    else:
        await ctx.send("You need to be in a voice channel to use this command.")


@bot.command()
@keywordCheck("leave")
async def leave(ctx):
    # Check if the bot is in a voice channel
    voice_client = ctx.voice_client
    if voice_client:
        await voice_client.disconnect()
        audio_queue = Queue()
        await ctx.send("I have left the voice channel.")
        await bot.change_presence(activity=discord.Game(name="Try !helpme"))

    else:
        await ctx.send("I'm not in a voice channel to leave.")


@bot.command()
@keywordCheck("play")
async def play(ctx, channel=None):
    # Ensure the bot is in a voice channel
    voice_client = ctx.voice_client
    if not voice_client:
        await ctx.send("I'm not in a voice channel. Use !join to add me to one.")
        return
    
    if channel is None:
        await ctx.send("You need to specify a channel. Use `!play <channel>`.")
        return

    channel = channel.lower()

    # Check if the provided channel exists in the dictionary
    if channel in channel_ids.keys():
        links = getStreamLinks(channel=channel)
    else:
        await ctx.send(f"Channel '{channel}' is not available.")
        return
    
    song_name = getCurrentSongName(channel)
    await bot.change_presence(activity=discord.Game(name=song_name))

    audio_queue = Queue()

    async def fetchAndQueueAudio(urls):
        global stop_requests
        while True:
            if stop_requests:
                stop_requests = False
                break
            
            audio_data, length_128_float, file_name = getNextAudioFile(urls=urls)
            
            with open(f"temp\\{file_name}", "wb") as binary_file:
                # Write bytes to file
                binary_file.write(audio_data)           
            
            mp3_file_name = convertToMp3(infile=f"temp\\{file_name}")
            os.remove(f"temp\\{file_name}")
            print(f"[GOOD] Removed temp file: {file_name}")
            
            audio_queue.put((audio_data, length_128_float, mp3_file_name))

            sleep_duration = length_128_float
            print("[GOOD] Got audiofile with size:", len(audio_data), "Sleeping for:", sleep_duration)
            await asyncio.sleep(sleep_duration)


    # Start fetching and queuing audio
    fetch_task = asyncio.create_task(fetchAndQueueAudio(urls=links))
    # Start playing audio
    play_task = asyncio.create_task(playAudio(audio_queue, voice_client, channel))
    
    await ctx.send(f'Playing some {channel} music. Use !stop to stop playback.')

    await fetch_task, play_task


@play.error
async def play_error(ctx, error):
    if isinstance(error, MissingRequiredArgument):
        await ctx.send("You need to specify a channel. Use `!play <channel>`.")


@bot.command()
@keywordCheck("stop")
async def stop(ctx):
    # Stop the audio playback and clear the queue

    audio_queue = Queue()
    voice_client = ctx.voice_client
    if voice_client.is_playing():
        voice_client.stop()
    await ctx.send("Playback stopped.")
    global stop_requests
    stop_requests = True
    await bot.change_presence(activity=discord.Game(name="Try !helpme"))


@bot.command()
@keywordCheck("ping")
async def ping(ctx, channel=None):

    await ctx.send("hi")


bot.run(constants.data.get("token"), root_logger=True)
